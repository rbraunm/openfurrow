# SPDX-License-Identifier: Apache-2.0
"""Adding and deleting scheduled tasks (decision 0041), for holders of manageTasks; the tasks page and each task's page
are the web interface's own."""

from __future__ import annotations

from flask import Blueprint, Response, request

from openfurrow.service.administration.modelForm import formItems, postedForm, startingText, valuesFrom
from openfurrow.service.administration.pages import Pages, refusals
from openfurrow.workspace import Workspace


def registerTaskPages(blueprint: Blueprint, workspace: Workspace, pages: Pages) -> None:

  @blueprint.get("/administration/tasks/add")
  def administrationTaskKinds() -> Response:
    """The kinds a new task can be of."""
    translator = pages.translator()
    return pages.render("administrationTaskKinds.html", translator, kinds=workspace.taskKinds())

  @blueprint.route("/administration/tasks/add/<kind>", methods=["GET", "POST"])
  def administrationTaskAdd(kind: str) -> Response:
    """Add a task of one kind: its name, and a field for each of the kind's parameters."""
    translator = pages.translator()
    found = [known for known in workspace.taskKinds() if known.name == kind]
    if not found:
      raise pages.unknown(translator, "taskKind", kind)
    model = found[0].parameters
    items = formItems(model)
    typed = startingText(items, translator.decimalSeparator)
    name = ""
    problems: list[str] = []
    if request.method == "POST":
      name = request.form.get("name", "").strip()
      items, typed = postedForm(model, request.form)
      if "more" not in request.form:
        values, unreadable = valuesFrom(items, typed, translator.decimalSeparator)
        problems = [translator.text(f"web.administration.form.{problem.reason}", field=problem.name) for problem in unreadable]
        if not problems:
          try:
            task = workspace.createTask(name, kind, values)
            return pages.back("web.task", translator, name=task.name)
          except refusals as error:
            problems = pages.reasons(error)
    return pages.render("administrationTaskAdd.html", translator, problems, kind=found[0], items=items, typed=typed, name=name,
                        helpOf=None)

  @blueprint.route("/administration/tasks/delete/<name>", methods=["GET", "POST"])
  def administrationTaskDelete(name: str) -> Response:
    """Deleting a task takes its runs with it, so it is asked twice: this page, then its button."""
    translator = pages.translator()
    task = workspace.task(name)
    problems: list[str] = []
    if request.method == "POST":
      try:
        workspace.deleteTask(name)
        return pages.back("web.tasks", translator)
      except refusals as error:
        problems = pages.reasons(error)
    kept = (None if task.ownerProvider is None
            else translator.text("web.administration.confirm.task.kept", provider=task.ownerProvider))
    return pages.confirm(translator, problems, "task", "tasks", task.name,
                         pages.addressOf("web.administrationTaskDelete", translator, name=name),
                         pages.addressOf("web.task", translator, name=name), blocked=kept)
