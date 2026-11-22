"""frontend/mock/api-routes.json, the list the mock backend is checked against, matches the API's routes."""
import pytest

from app import api_routes


@pytest.mark.skipif(not api_routes.FILE.exists(), reason="no frontend/ beside backend/ (as in the API's image)")
def test_the_mock_route_list_is_up_to_date():
    written = api_routes.FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert written == api_routes.as_text(), (
        "The API's routes changed: run `python -m app.api_routes` in backend/, then `npm run check:mock` in frontend/ "
        "and mirror the new route in the mock"
    )
