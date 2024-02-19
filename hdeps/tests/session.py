import unittest

from ..session import get_cached_retry_session, get_retry_session


class LiveSessionTest(unittest.TestCase):
    def test_just_call_get_retry_session(self) -> None:
        session = get_retry_session()
        session.get("https://httpbin.org/status/200,503")

    def test_just_call_get_cached_retry_session(self) -> None:
        session = get_cached_retry_session()
        session.get("https://httpbin.org/status/200,503")
