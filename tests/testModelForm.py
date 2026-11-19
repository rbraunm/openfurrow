# SPDX-License-Identifier: Apache-2.0
"""The form a pydantic model makes (worklist GOV-6): a field for each of the model's own, of the kind its type calls
for, and what was typed handed back as the data the model validates."""

from enum import Enum

import pytest
from pydantic import BaseModel
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import BadRequest

from openfurrow.service.administration.modelForm import (FieldKind, FormProblem, fields, formItems, maximumRows, postedForm,
                                                          startingText, valuesFrom)


class Colour(str, Enum):
  red = "red"
  green = "green"


class Pair(BaseModel):
  left: str
  right: str | None = None


class Everything(BaseModel):
  title: str
  note: str | None = "a note"
  count: int = 3
  ratio: float = 0.5
  enabled: bool = True
  colour: Colour = Colour.green
  lines: list[str] = []
  certificate: str | None = None
  pair: Pair | None = None
  pairs: list[Pair] = []
  extra: dict[str, int] | None = None


def testAFieldIsMadeForEachOfTheModelsOwnOfTheKindItsTypeCallsFor():
  items = formItems(Everything, frozenset({"certificate"}))
  found = {field.name: (field.kind, field.optional, field.default) for field in fields(items)}
  assert found == {
    "title": (FieldKind.text, False, ""),
    "note": (FieldKind.text, True, "a note"),
    "count": (FieldKind.integer, False, "3"),
    "ratio": (FieldKind.number, False, "0.5"),
    "enabled": (FieldKind.flag, False, "yes"),
    "colour": (FieldKind.choice, False, "green"),
    "lines": (FieldKind.lines, False, ""),
    "certificate": (FieldKind.longText, True, ""),
    "pair.left": (FieldKind.text, False, ""),
    "pair.right": (FieldKind.text, True, ""),
    "pairs.0.left": (FieldKind.text, False, ""),
    "pairs.0.right": (FieldKind.text, True, ""),
    "extra": (FieldKind.json, True, ""),
  }
  assert next(field for field in fields(items) if field.name == "colour").choices == ("red", "green")
  assert [(item.name, item.optional, item.repeated, len(item.rows)) for item in items if hasattr(item, "rows")] == [
    ("pair", True, False, 1), ("pairs", False, True, 1)]
  assert startingText(items, ",")["ratio"] == "0,5" and startingText(items, ".")["ratio"] == "0.5"


def testWhatWasTypedBecomesTheDataTheModelValidates():
  form = MultiDict({
    "title": "  A title ", "note": "", "count": "12", "ratio": "0,25", "colour": "red", "lines": "one\r\n\r\n two \r\n",
    "certificate": "-----BEGIN-----\r\nabc\r\n-----END-----\r\n", "pair.left": "", "pair.right": "",
    "pairs.rows": "3", "pairs.0.left": "a", "pairs.0.right": "", "pairs.1.left": "", "pairs.1.right": "",
    "pairs.2.left": "c", "pairs.2.right": "d", "extra": '{"depth": 2}',
  })
  items, typed = postedForm(Everything, form, frozenset({"certificate"}))
  assert typed["title"] == "  A title " and typed["enabled"] == ""
  values, problems = valuesFrom(items, typed, ",")
  assert problems == []
  assert values == {
    "title": "A title", "note": None, "count": "12", "ratio": "0.25", "enabled": False, "colour": "red",
    "lines": ["one", "two"], "certificate": "-----BEGIN-----\nabc\n-----END-----\n", "pair": None,
    "pairs": [{"left": "a", "right": None}, {"left": "c", "right": "d"}], "extra": {"depth": 2},
  }
  model = Everything.model_validate(values)
  assert (model.count, model.ratio, model.colour, model.pairs[1].right) == (12, 0.25, Colour.red, "d")


def testAnEmptyFieldTheModelNeedsAndTextThatIsNotJSONAreProblemsByName():
  form = MultiDict({"title": "", "note": "kept", "count": "", "ratio": "1.5", "enabled": "yes", "colour": "green",
                    "lines": "", "certificate": "", "pair.left": "", "pair.right": "only the optional one",
                    "pairs.rows": "1", "pairs.0.left": "", "pairs.0.right": "", "extra": "{not json"})
  items, typed = postedForm(Everything, form)
  values, problems = valuesFrom(items, typed, ".")
  assert problems == [FormProblem("title", "needsValue"), FormProblem("count", "needsValue"),
                      FormProblem("pair.left", "needsValue"), FormProblem("extra", "notJSON")]
  assert values["note"] == "kept" and values["enabled"] is True and values["pairs"] == [] and values["lines"] == []


def testARowIsAddedWhereItsButtonWasPressedAndARowCountOutOfRangeIsRefused():
  form = MultiDict({"title": "t", "pairs.rows": "2", "pairs.0.left": "a", "pairs.1.left": "b", "more": "pairs"})
  items, typed = postedForm(Everything, form)
  assert [field.name for field in fields(items) if field.name.startswith("pairs.")] == [
    "pairs.0.left", "pairs.0.right", "pairs.1.left", "pairs.1.right", "pairs.2.left", "pairs.2.right"]
  assert (typed["pairs.0.left"], typed["pairs.1.left"], typed["pairs.2.left"]) == ("a", "b", "")
  for count in ("0", str(maximumRows + 1), "many", None):
    bad = MultiDict({"title": "t"} | ({} if count is None else {"pairs.rows": count}))
    with pytest.raises(BadRequest):
      postedForm(Everything, bad)
