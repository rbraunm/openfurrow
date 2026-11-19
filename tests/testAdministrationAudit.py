# SPDX-License-Identifier: Apache-2.0
"""The audit log on the web and in the facade (worklist GOV-6; decision 0038): newest first, a page at a time, its
detail readable, and narrowed by who acted, the action, where and when."""

import datetime
import html
import re

import pytest
from markupsafe import escape

from openfurrow import Workspace
from openfurrow.i18n import translatorFor
from openfurrow.workspace import EventFilter

from administrationHelpers import origin, seededStore, signedIn, text, trialCode
from storeHelpers import standardPath

english = translatorFor("en-US")
placeScope = f"place:{standardPath}"
trialScope = f"trial:{trialCode}"


@pytest.fixture
def location(newStore, validPackageDict):
  return seededStore(newStore, validPackageDict)


def listedOn(page: str) -> list[int]:
  return [int(number) for number in re.findall(r'<tr id="event-(\d+)">', page)]


def linkNamed(page: str, key: str) -> str | None:
  found = re.search(rf'<a href="([^"]+)">{re.escape(english.text(key))}</a>', page)
  return None if found is None else html.unescape(found.group(1))


def testTheAuditLogIsNewestFirstAPageAtATimeWithItsDetailReadable(location):
  operator = Workspace.open(location)
  for hours in range(1, 61):
    operator.setSetting("server", "identity.sessionHours", hours)
  admin = signedIn(location, "admin")
  every = [event.eventID for event in operator.auditEvents(limit=1000)]
  assert len(every) > 60 and every == sorted(every, reverse=True)

  first = text(admin.get("/administration/audit"))
  assert listedOn(first) == every[:50]
  assert linkNamed(first, "web.administration.audit.newest") is None
  second = text(admin.get(linkNamed(first, "web.administration.audit.older")))
  assert listedOn(second) == every[50:100] and len(every) <= 100
  assert linkNamed(second, "web.administration.audit.older") is None
  assert listedOn(text(admin.get(linkNamed(second, "web.administration.audit.newest")))) == every[:50]

  assert '<span class="code" dir="auto">admin</span>' in first and english.text("web.administration.audit.actor.operator") in first
  assert english.text("web.administration.audit.actor.account") in first
  assert '<td class="code" dir="ltr">setting.set</td>' in first and english.text("web.administration.scope.named.server") in first
  changed = ('<dt class="code">after</dt><dd><dl class="detail">'
             '<div><dt class="code">source</dt><dd><span dir="auto">server</span></dd></div>'
             '<div><dt class="code">value</dt><dd><span dir="auto">60</span></dd></div></dl></dd>')
  assert changed in re.sub(r">\s+<", "><", first)
  assert "{&#34;" not in first and '{"' not in first


def testTheAuditLogIsNarrowedByWhoTheActionWhereAndWhen(location):
  operator = Workspace.open(location)
  operator.addPlace(None, "station2", "A second station")
  admin = signedIn(location, "admin")
  assert admin.post("/administration/groups", data={"name": "team"}, headers=origin).status_code == 302
  change = {"action": "set", "key": "analysis.meanComparison", "value": "lsd"}
  assert admin.post(f"/administration/settings?scope={trialScope}", data=change, headers=origin).status_code == 302
  everything = operator.auditEvents(limit=1000)

  def kept(keep) -> list[int]:
    return [event.eventID for event in everything if keep(event)]

  def listed(**chosen) -> list[int]:
    answer = admin.get("/administration/audit", query_string=chosen)
    assert answer.status_code == 200, chosen
    return listedOn(text(answer))

  assert listed() == kept(lambda event: True)
  byAdmin = listed(actor="admin")
  assert byAdmin == kept(lambda event: event.actorName == "admin")
  assert [event.action for event in everything if event.eventID in byAdmin] == ["setting.set", "group.create", "signIn"]
  assert listed(actor="operator") == kept(lambda event: event.actorKind == "operator")
  assert listed(actor="nobody") == []
  roles = listed(action="role.")
  assert roles == kept(lambda event: event.action.startswith("role.")) and len(roles) == 2
  assert listed(action="setting.set", actor="admin") == kept(
    lambda event: event.action == "setting.set" and event.actorName == "admin")
  atTrial = listed(scope=trialScope)
  assert atTrial == kept(lambda event: event.scope == trialScope) and len(atTrial) == 2
  assert listed(scope=placeScope) == kept(lambda event: event.scope in (placeScope, trialScope))
  inStation = listed(scope="place:station")
  assert inStation == kept(lambda event: event.scope == "place:station" or event.scope.startswith("place:station/")
                           or event.scope == trialScope)
  assert len(inStation) == 5 and listed(scope="place:station2") == kept(lambda event: event.scope == "place:station2")

  days = sorted({datetime.date.fromisoformat(event.at[:10]) for event in everything})
  oneDay = datetime.timedelta(days=1)
  assert listed(since=days[0].isoformat(), until=days[-1].isoformat()) == kept(lambda event: True)
  assert listed(until=(days[0] - oneDay).isoformat()) == []
  assert listed(since=(days[-1] + oneDay).isoformat()) == []
  assert listed(since=days[-1].isoformat(), actor="admin") == kept(
    lambda event: event.actorName == "admin" and event.at[:10] == days[-1].isoformat())

  narrowed = text(admin.get("/administration/audit", query_string={"actor": "admin", "action": "group."}))
  assert 'name="actor" dir="auto" autocomplete="off" value="admin"' in narrowed
  assert 'name="action" dir="ltr" autocomplete="off" value="group."' in narrowed
  assert english.text("web.administration.audit.clearFilters") in narrowed
  assert english.text("web.administration.audit.none") in text(admin.get("/administration/audit?actor=nobody"))
  bad = admin.get("/administration/audit?since=yesterday&actor=admin")
  reason = english.text("web.administration.audit.notADate", field=english.text("web.administration.audit.since"), typed="yesterday")
  assert bad.status_code == 400 and str(escape(reason)) in text(bad)
  assert 'value="yesterday"' in text(bad) and 'value="admin"' in text(bad)

  chosen = operator.auditEvents("server", chosen=EventFilter(actor="admin", action="group."))
  assert [(event.action, event.detail) for event in chosen] == [("group.create", {"group": "team"})]
  newest = everything[0].eventID
  assert [event.eventID for event in operator.auditEvents(limit=2, chosen=EventFilter(before=newest))] == [
    event.eventID for event in everything[1:3]]
