# SPDX-License-Identifier: Apache-2.0
"""Bar charts of separated means, drawn as SVG (decision 0032).

One chart per table of means: a bar per treatment or factor level from a zero baseline,
an error bar of one standard error of a mean on the analysis' own error, and the letters
of the table above it. Means and error bars are on the original scale; after a transform
the bar ends are back-transformed, so they need not be symmetric. Drawn natively, with
no plotting library (decision 0002); the table beside each chart is its text view.
"""

from __future__ import annotations

import html
import math

from pydantic import BaseModel, ConfigDict

from openfurrow.i18n import Translator

plotHeight = 220.0
bandWidth = 64.0
barWidth = 24.0
topMargin = 24.0
leftMargin = 64.0
rightMargin = 16.0
cornerRadius = 4.0
capWidth = 10.0
tickTarget = 5


class ChartBar(BaseModel):
  """One bar: its label, mean, the ends of its error bar, and its letters if any."""

  model_config = ConfigDict(extra="forbid")

  label: str
  mean: float
  low: float
  high: float
  group: str | None = None


class MeansChart(BaseModel):
  """A bar chart of the means of one table, in the order the table lists them."""

  model_config = ConfigDict(extra="forbid")

  title: str
  axisTitle: str
  caption: str
  decimals: int
  bars: list[ChartBar]


def niceStep(span: float, target: int = tickTarget) -> float:
  """A tick step of 1, 2, 2.5 or 5 times a power of ten giving about `target` ticks over `span`."""
  if span <= 0.0:
    raise ValueError(f"a chart needs a positive span, got {span}")
  raw = span / target
  power = 10.0 ** math.floor(math.log10(raw))
  for multiple in (1.0, 2.0, 2.5, 5.0, 10.0):
    if raw <= multiple * power * (1.0 + 1e-9):
      return multiple * power
  raise AssertionError("unreachable")


def axisRange(chart: MeansChart) -> tuple[float, float, float]:
  """The value axis: from zero or below to the highest error bar end, on whole steps."""
  low = min(0.0, *(bar.low for bar in chart.bars), *(bar.mean for bar in chart.bars))
  high = max(0.0, *(bar.high for bar in chart.bars), *(bar.mean for bar in chart.bars))
  if high == low:
    high = low + 1.0
  step = niceStep(high - low)
  return math.floor(low / step + 1e-9) * step, math.ceil(high / step - 1e-9) * step, step


def _tickDecimals(step: float) -> int:
  decimals = 0
  while abs(step * 10 ** decimals - round(step * 10 ** decimals)) > 1e-9 and decimals < 6:
    decimals += 1
  return decimals


def meansChartSvg(chart: MeansChart, translator: Translator) -> str:
  """The chart as an inline SVG element, styled by the page's chart classes."""
  if not chart.bars:
    raise ValueError("a chart needs at least one bar")
  for bar in chart.bars:
    if not bar.low <= bar.mean <= bar.high:
      raise ValueError(f"bar '{bar.label}': the error bar {bar.low}..{bar.high} does not hold the mean {bar.mean}")
  bottom, top, step = axisRange(chart)
  rotate = any(len(bar.label) > 7 for bar in chart.bars)
  labelSpace = 12.0 + (6.5 * max(len(bar.label) for bar in chart.bars) * 0.7 if rotate else 16.0)
  width = leftMargin + bandWidth * len(chart.bars) + rightMargin
  height = topMargin + plotHeight + labelSpace + 24.0

  def y(value: float) -> float:
    return topMargin + plotHeight * (top - value) / (top - bottom)

  zero = y(0.0)
  escape = html.escape
  parts = [
    f'<svg class="means-chart" role="img" aria-label="{escape(chart.title)}" viewBox="0 0 {width:.0f} {height:.0f}" '
    f'width="{width:.0f}" height="{height:.0f}" direction="ltr" xmlns="http://www.w3.org/2000/svg">',
    f"<title>{escape(chart.title)}</title>",
  ]
  tickDecimals = _tickDecimals(step)
  tickCount = round((top - bottom) / step)
  for index in range(tickCount + 1):
    value = bottom + index * step
    position = y(value)
    parts.append(
      f'<line class="chart-grid" x1="{leftMargin:.1f}" x2="{width - rightMargin:.1f}" y1="{position:.1f}" y2="{position:.1f}"/>'
      f'<text class="chart-tick" x="{leftMargin - 8:.1f}" y="{position + 4:.1f}" text-anchor="end">'
      f"{escape(translator.number(value, decimals=tickDecimals))}</text>"
    )
  parts.append(
    f'<text class="chart-axis-title" transform="translate(14 {topMargin + plotHeight / 2:.1f}) rotate(-90)" '
    f'text-anchor="middle">{escape(chart.axisTitle)}</text>'
  )
  for index, bar in enumerate(chart.bars):
    center = leftMargin + bandWidth * (index + 0.5)
    left, right = center - barWidth / 2, center + barWidth / 2
    end = y(bar.mean)
    shown = translator.number(bar.mean, decimals=chart.decimals)
    tip = f"{bar.label}: {shown} ({translator.number(bar.low, decimals=chart.decimals)} - {translator.number(bar.high, decimals=chart.decimals)})"
    if bar.group:
      tip += f" {bar.group}"
    parts.append(f'<g class="chart-mark"><title>{escape(tip)}</title>')
    parts.append(
      f'<rect class="chart-hit" x="{center - bandWidth / 2:.1f}" y="{topMargin:.1f}" width="{bandWidth:.1f}" height="{plotHeight:.1f}"/>'
    )
    parts.append(f'<path class="chart-bar" d="{_barPath(left, right, zero, end)}"/>')
    lowEnd, highEnd = y(bar.low), y(bar.high)
    parts.append(
      f'<path class="chart-error" d="M{center:.1f} {lowEnd:.1f}V{highEnd:.1f}'
      f'M{center - capWidth / 2:.1f} {lowEnd:.1f}h{capWidth:.1f}M{center - capWidth / 2:.1f} {highEnd:.1f}h{capWidth:.1f}"/>'
    )
    if bar.group:
      above = bar.mean >= 0.0
      letterY = (min(highEnd, end) - 6.0) if above else (max(lowEnd, end) + 14.0)
      parts.append(f'<text class="chart-letter" x="{center:.1f}" y="{letterY:.1f}" text-anchor="middle">{escape(bar.group)}</text>')
    labelY = topMargin + plotHeight + 18.0
    if rotate:
      parts.append(
        f'<text class="chart-label" transform="translate({center + 4:.1f} {labelY - 4:.1f}) rotate(-35)" text-anchor="end">'
        f"{escape(bar.label)}</text>"
      )
    else:
      parts.append(f'<text class="chart-label" x="{center:.1f}" y="{labelY:.1f}" text-anchor="middle">{escape(bar.label)}</text>')
    parts.append("</g>")
  parts.append(
    f'<line class="chart-baseline" x1="{leftMargin:.1f}" x2="{width - rightMargin:.1f}" y1="{zero:.1f}" y2="{zero:.1f}"/>'
  )
  parts.append("</svg>")
  return "".join(parts)


def meansFigure(chart: MeansChart, translator: Translator) -> str:
  """The chart with its caption, as a figure element."""
  return (
    f'<figure class="chart">{meansChartSvg(chart, translator)}'
    f"<figcaption>{html.escape(chart.caption)}</figcaption></figure>"
  )


def _barPath(left: float, right: float, baseline: float, end: float) -> str:
  """A bar square at the baseline with its data end rounded, upward or downward."""
  length = abs(baseline - end)
  radius = min(cornerRadius, length, (right - left) / 2)
  if end <= baseline:
    return (
      f"M{left:.1f} {baseline:.1f}V{end + radius:.1f}Q{left:.1f} {end:.1f} {left + radius:.1f} {end:.1f}"
      f"H{right - radius:.1f}Q{right:.1f} {end:.1f} {right:.1f} {end + radius:.1f}V{baseline:.1f}Z"
    )
  return (
    f"M{left:.1f} {baseline:.1f}V{end - radius:.1f}Q{left:.1f} {end:.1f} {left + radius:.1f} {end:.1f}"
    f"H{right - radius:.1f}Q{right:.1f} {end:.1f} {right:.1f} {end - radius:.1f}V{baseline:.1f}Z"
  )
