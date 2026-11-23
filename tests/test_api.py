from datetime import timedelta

import pytest

from .conftest import PASSWORD, slot_start

pytestmark = pytest.mark.django_db
HOUR = timedelta(hours=1)


def payload(court, start, hours=1):
    return {"court": court.pk, "start_time": start.isoformat(), "end_time": (start + hours * HOUR).isoformat()}


def test_register_login_me(client_for):
    c = client_for()
    r = c.post("/api/v1/auth/register/", {"email": "New@Test.com", "password": PASSWORD, "first_name": "New"}, format="json")
    assert r.status_code == 201 and "password" not in r.data
    tok = c.post("/api/v1/auth/token/", {"email": "new@test.com", "password": PASSWORD}, format="json")
    assert tok.status_code == 200
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {tok.data['access']}")
    me = c.get("/api/v1/auth/me/")
    assert me.data["email"] == "new@test.com" and me.data["role"] == "customer"


def test_cannot_self_register_as_owner(client_for):
    r = client_for().post(
        "/api/v1/auth/register/", {"email": "x@test.com", "password": PASSWORD, "role": "admin"}, format="json"
    )
    assert r.status_code == 201
    assert r.data.get("role") is None
    from apps.accounts.models import User
    assert User.objects.get(email="x@test.com").role == "customer"


def test_venues_are_public_and_role_protected(client_for, owner, customer, venue):
    assert client_for().get("/api/v1/venues/").status_code == 200
    body = {"name": "New Venue", "address": "x", "city": "Pune", "opening_time": "06:00", "closing_time": "22:00"}
    assert client_for(customer).post("/api/v1/venues/", body, format="json").status_code == 403
    r = client_for(owner).post("/api/v1/venues/", body, format="json")
    assert r.status_code == 201 and r.data["slug"] == "new-venue"


def test_owner_cannot_modify_another_owners_venue(client_for, other_owner, venue):
    r = client_for(other_owner).patch(f"/api/v1/venues/{venue.pk}/", {"name": "Hijack"}, format="json")
    assert r.status_code == 404


def test_owner_cannot_add_court_to_foreign_venue(client_for, other_owner, venue):
    body = {"venue": venue.pk, "name": "Evil", "sport": "football", "base_price_per_hour": "100"}
    assert client_for(other_owner).post("/api/v1/courts/", body, format="json").status_code == 400


def test_availability_reflects_new_booking_immediately(client_for, customer, court, venue, django_capture_on_commit_callbacks):
    s = slot_start(venue, 18)
    c = client_for(customer)
    url = f"/api/v1/courts/{court.pk}/availability/?date={s.date().isoformat()}"
    before = {x["start"]: x for x in client_for().get(url).data["slots"]}
    assert before[s.isoformat()]["available"] is True

    with django_capture_on_commit_callbacks(execute=True):
        assert c.post("/api/v1/bookings/", payload(court, s), format="json").status_code == 201

    after = {x["start"]: x for x in client_for().get(url).data["slots"]}
    assert after[s.isoformat()]["available"] is False
    assert after[(s + HOUR).isoformat()]["available"] is True


def test_quote_endpoint(client_for, court, venue):
    s = slot_start(venue, 10)
    r = client_for().get(f"/api/v1/courts/{court.pk}/quote/", {"start_time": s.isoformat(), "end_time": (s + 2 * HOUR).isoformat()})
    assert r.status_code == 200 and str(r.data["total"]) == "2000.00" and len(r.data["slots"]) == 2


def test_booking_flow_and_conflict_envelope(client_for, customer, other_customer, court, venue):
    s = slot_start(venue, 18)
    r = client_for(customer).post("/api/v1/bookings/", payload(court, s), format="json")
    assert r.status_code == 201 and r.data["status"] == "pending"
    dup = client_for(other_customer).post("/api/v1/bookings/", payload(court, s), format="json")
    assert dup.status_code == 409 and dup.data["error"]["code"] == "slot_unavailable"


def test_validation_error_envelope(client_for, customer, court, venue):
    r = client_for(customer).post("/api/v1/bookings/", payload(court, slot_start(venue, 3)), format="json")
    assert r.status_code == 400 and r.data["error"]["code"] == "invalid_booking_request"


def test_booking_requires_auth(client_for, court, venue):
    assert client_for().post("/api/v1/bookings/", payload(court, slot_start(venue, 18)), format="json").status_code == 401


def test_bookings_are_private_to_their_owner(client_for, customer, other_customer, owner, court, venue):
    s = slot_start(venue, 18)
    b = client_for(customer).post("/api/v1/bookings/", payload(court, s), format="json").data
    assert client_for(other_customer).get(f"/api/v1/bookings/{b['id']}/").status_code == 404
    assert client_for(other_customer).get("/api/v1/bookings/").data["count"] == 0
    assert client_for(owner).get(f"/api/v1/bookings/{b['id']}/").status_code == 200  # venue owner can see
    assert client_for(other_customer).post(f"/api/v1/bookings/{b['id']}/cancel/").status_code == 404


def test_health(client_for):
    assert client_for().get("/health/").status_code == 200
