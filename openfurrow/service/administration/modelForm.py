# SPDX-License-Identifier: Apache-2.0
"""A form for a pydantic model: one field for each field of the model, so a model that gains one gains it on the page.

An identity provider's settings (decision 0040) and a task kind's parameters (decision 0041) are pydantic models, and
the model is what checks them. This module only turns a model into the fields of a form and what was typed into them
back into the data the model validates: text, numbers, flags, one of an enumeration, a list of lines, a model inside
the model (a group of fields, left empty when it is optional), and a list of such models (rows, with a button for
another one). A field of any other type is typed as JSON.
"""

from __future__ import annotations

import json
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel
from werkzeug.exceptions import BadRequest

maximumRows = 50


class FieldKind(str, Enum):
  text = "text"
  longText = "longText"
  integer = "integer"
  number = "number"
  flag = "flag"
  choice = "choice"
  lines = "lines"
  json = "json"


@dataclass(frozen=True)
class FormField:
  """One field: `name` is what the form posts (its path in the model), `setting` its own name in its model."""

  name: str
  setting: str
  kind: FieldKind
  optional: bool
  choices: tuple[str, ...]
  default: str


@dataclass(frozen=True)
class FieldGroup:
  """A model inside the model: one row of its fields, or for a list of them as many rows as were asked for."""

  name: str
  setting: str
  optional: bool
  repeated: bool
  rows: tuple[tuple, ...]


@dataclass(frozen=True)
class FormProblem:
  """A field whose text cannot be handed to the model at all; `reason` is 'needsValue' or 'notJSON'."""

  name: str
  reason: str


def _withoutNone(annotation) -> tuple[object, bool]:
  if typing.get_origin(annotation) in (typing.Union, types.UnionType):
    members = [member for member in typing.get_args(annotation) if member is not type(None)]
    if len(members) == 1 and len(members) < len(typing.get_args(annotation)):
      return members[0], True
  return annotation, False


def _isModel(annotation) -> bool:
  return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _listOf(annotation):
  return typing.get_args(annotation)[0] if typing.get_origin(annotation) is list else None


def _kind(plain, setting: str, longText: frozenset[str]) -> FieldKind:
  if plain is bool:
    return FieldKind.flag
  if plain is int:
    return FieldKind.integer
  if plain is float:
    return FieldKind.number
  if plain is str:
    return FieldKind.longText if setting in longText else FieldKind.text
  if isinstance(plain, type) and issubclass(plain, Enum):
    return FieldKind.choice
  if _listOf(plain) is str:
    return FieldKind.lines
  return FieldKind.json


def _defaultText(kind: FieldKind, value) -> str:
  if value is None:
    return ""
  if kind is FieldKind.flag:
    return "yes" if value else ""
  if kind is FieldKind.choice:
    return value.value
  if kind is FieldKind.lines:
    return "\n".join(value)
  if kind is FieldKind.json:
    return json.dumps(value)
  return str(value)


def formItems(model: type[BaseModel], longText: frozenset[str] = frozenset(),
              rowsOf: Callable[[str], int] = lambda name: 1, prefix: str = "") -> list[FormField | FieldGroup]:
  """The fields of a form for `model`, in the model's order; `rowsOf` says how many rows a list of models shows."""
  items: list[FormField | FieldGroup] = []
  for setting, field in model.model_fields.items():
    name = f"{prefix}{setting}"
    plain, optional = _withoutNone(field.annotation)
    if _isModel(plain):
      items.append(FieldGroup(name, setting, optional, False, (tuple(formItems(plain, longText, rowsOf, f"{name}.")),)))
    elif _isModel(_listOf(plain)):
      rows = tuple(tuple(formItems(_listOf(plain), longText, rowsOf, f"{name}.{row}.")) for row in range(rowsOf(name)))
      items.append(FieldGroup(name, setting, optional, True, rows))
    else:
      kind = _kind(plain, setting, longText)
      choices = tuple(member.value for member in plain) if kind is FieldKind.choice else ()
      default = None if field.is_required() else field.get_default(call_default_factory=True)
      items.append(FormField(name, setting, kind, optional, choices, _defaultText(kind, default)))
  return items


def fields(items) -> list[FormField]:
  found: list[FormField] = []
  for item in items:
    if isinstance(item, FieldGroup):
      for row in item.rows:
        found += fields(row)
    else:
      found.append(item)
  return found


def startingText(items, decimalSeparator: str) -> dict[str, str]:
  """What each field shows before anything is typed: its default, a number in the reader's decimal mark."""
  return {field.name: field.default.replace(".", decimalSeparator) if field.kind is FieldKind.number else field.default
          for field in fields(items)}


def postedForm(model: type[BaseModel], form, longText: frozenset[str] = frozenset()) -> tuple[list, dict[str, str]]:
  """The form as it was posted: its fields, with the rows it had and one more where its button was pressed, and what
  was typed in each, as typed."""
  def rowsOf(name: str) -> int:
    rows = form.get(f"{name}.rows", type=int)
    if rows is None or not 1 <= rows <= maximumRows:
      raise BadRequest(f"the form's count of {name} rows is not a number from 1 to {maximumRows}")
    return min(maximumRows, rows + 1) if form.get("more") == name else rows

  items = formItems(model, longText, rowsOf)
  return items, {field.name: form.get(field.name, "") for field in fields(items)}


def _isEmpty(row, typed: dict[str, str]) -> bool:
  return not any(typed[field.name].strip() for field in fields(row) if field.kind is not FieldKind.choice)


def valuesFrom(items, typed: dict[str, str], decimalSeparator: str) -> tuple[dict, list[FormProblem]]:
  """What was typed, as data for the model to validate, and the fields that cannot be handed to it. An empty field
  is no value where the model allows none and a problem elsewhere; an optional group or a row left empty is left out."""
  values: dict = {}
  problems: list[FormProblem] = []
  for item in items:
    if isinstance(item, FieldGroup):
      rows = []
      for row in item.rows:
        if (item.optional or item.repeated) and _isEmpty(row, typed):
          continue
        rowValues, rowProblems = valuesFrom(row, typed, decimalSeparator)
        rows.append(rowValues)
        problems += rowProblems
      if item.repeated:
        values[item.setting] = rows
      elif rows:
        values[item.setting] = rows[0]
      else:
        values[item.setting] = None
      continue
    text = typed[item.name].strip()
    if item.kind is FieldKind.flag:
      values[item.setting] = text == "yes"
    elif item.kind is FieldKind.lines:
      values[item.setting] = [line.strip() for line in text.splitlines() if line.strip()]
    elif not text:
      if item.optional:
        values[item.setting] = None
      else:
        problems.append(FormProblem(item.name, "needsValue"))
    elif item.kind is FieldKind.number:
      values[item.setting] = text.replace(decimalSeparator, ".")
    elif item.kind is FieldKind.json:
      try:
        values[item.setting] = json.loads(text)
      except json.JSONDecodeError:
        problems.append(FormProblem(item.name, "notJSON"))
    elif item.kind is FieldKind.longText:
      # A browser posts a text area's lines ended with CR LF; a certificate's own line ending is LF.
      values[item.setting] = "\n".join(text.splitlines()) + "\n"
    else:
      values[item.setting] = text
  return values, problems
