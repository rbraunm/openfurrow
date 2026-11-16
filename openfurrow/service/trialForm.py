# SPDX-License-Identifier: Apache-2.0
"""The new-trial form: what a person types, turned into a trial package (worklist USR-1).

The form covers what most trials need: the trial's details, its treatments and their
roles, the number of blocks, where the layout comes from, and the assessments with their
limits or categories. Each assessment is one rating taken once, under one code. Trials
with product lines, applications, factors or checks are written as a trial file.
"""

from __future__ import annotations

import re
import secrets

from openfurrow.schema.trialPackage import RandomizationMethod
from openfurrow.version import schemaVersion

trialFields = ("trialCode", "title", "crop", "season", "site", "objective", "investigator", "organization")
optionalTrialFields = {"investigator", "organization"}
treatmentFields = ("code", "name", "role")
assessmentFields = ("code", "name", "dataType", "unit", "minValue", "maxValue", "categories")
startingRows = {"treatments": 6, "assessments": 3}
moreRows = 4
_number = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


class FormProblem(ValueError):
  """Something typed in the form that cannot make a trial; `reasonKey` names it for display."""

  def __init__(self, reasonKey: str, **placeholders: str) -> None:
    super().__init__(reasonKey)
    self.reasonKey = reasonKey
    self.placeholders = placeholders


def emptyForm() -> dict:
  return {
    "trial": {field: "" for field in trialFields},
    "treatments": [dict.fromkeys(treatmentFields, "") for _ in range(startingRows["treatments"])],
    "assessments": [
      dict.fromkeys(assessmentFields, "") | {"dataType": "numeric"} for _ in range(startingRows["assessments"])
    ],
    "replications": "4",
    "layoutSource": "generate",
    "seed": "",
  }


def formFromRequest(form) -> dict:
  """What was typed, as it was typed, with the rows a "more rows" button asked for."""
  def rows(prefix: str, fields: tuple[str, ...]) -> list[dict]:
    count = int(form.get(f"{prefix}Rows", startingRows[prefix]))
    typed = [{field: form.get(f"{prefix}-{index}-{field}", "") for field in fields} for index in range(count)]
    if form.get("more") == prefix:
      typed += [dict.fromkeys(fields, "") | ({"dataType": "numeric"} if prefix == "assessments" else {})
                for _ in range(moreRows)]
    return typed

  return {
    "trial": {field: form.get(field, "") for field in trialFields},
    "treatments": rows("treatments", treatmentFields),
    "assessments": rows("assessments", assessmentFields),
    "replications": form.get("replications", ""),
    "layoutSource": form.get("layoutSource", "generate"),
    "seed": form.get("seed", ""),
  }


def packageFromForm(typed: dict, decimalSeparator: str) -> dict:
  """The trial package the form describes, as data for the schema to validate.

  Blank rows are skipped. A generated layout without a seed gets a fresh one, which is
  then recorded with the trial like any seed.
  """
  def number(text: str, field: str, row: int):
    text = text.strip()
    if not text:
      return None
    if decimalSeparator != "." and decimalSeparator in text and "." in text:
      raise FormProblem("web.form.problem.number", field=field, row=str(row))
    text = text.replace(decimalSeparator, ".")
    if not _number.match(text):
      raise FormProblem("web.form.problem.number", field=field, row=str(row))
    return float(text)

  trial = {field: typed["trial"][field].strip() for field in trialFields}
  for field in optionalTrialFields:
    if not trial[field]:
      trial[field] = None
  treatments = []
  for row in typed["treatments"]:
    if not any(row[field].strip() for field in ("code", "name")):
      continue
    treatment = {"treatmentCode": row["code"].strip(), "name": row["name"].strip()}
    if row["role"]:
      treatment["role"] = row["role"]
    treatments.append(treatment)
  ratings, assessments = [], []
  for index, row in enumerate(typed["assessments"], start=1):
    if not any(row[field].strip() for field in ("code", "name")):
      continue
    code = row["code"].strip()
    rating = {"ratingCode": code, "name": row["name"].strip(), "dataType": row["dataType"]}
    if row["dataType"] == "numeric":
      if row["unit"].strip():
        rating["unit"] = row["unit"].strip()
      for field in ("minValue", "maxValue"):
        value = number(row[field], field, index)
        if value is not None:
          rating[field] = value
    else:
      rating["allowedValues"] = [value.strip() for value in row["categories"].split(",") if value.strip()]
    ratings.append(rating)
    assessments.append({"assessmentCode": code, "ratingCode": code})
  try:
    replications = int(typed["replications"].strip())
  except ValueError as error:
    raise FormProblem("web.form.problem.replications") from error
  design: dict = {"designType": "rcbd", "replications": replications}
  if typed["layoutSource"] == "upload":
    design["randomizationMethod"] = RandomizationMethod.imported.value
  else:
    design["randomizationMethod"] = RandomizationMethod.sha256FisherYates1.value
    seed = typed["seed"].strip()
    if seed and not seed.isdigit():
      raise FormProblem("web.form.problem.seed")
    design["randomizationSeed"] = int(seed) if seed else secrets.randbelow(10 ** 9)
  return {
    "schemaVersion": schemaVersion,
    "trial": trial,
    "treatments": treatments,
    "design": design,
    "ratings": ratings,
    "assessments": assessments,
  }
