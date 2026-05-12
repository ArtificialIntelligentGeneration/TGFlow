import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from pyrogram import enums

from parsing_engine import ParsingEngine


def make_user(
    user_id: int,
    *,
    username: str = "",
    first_name: str = "User",
    last_name: str = "",
    is_bot: bool = False,
    is_deleted: bool = False,
    status=None,
    last_online_date=None,
):
    return SimpleNamespace(
        id=user_id,
        username=username or None,
        first_name=first_name,
        last_name=last_name,
        is_bot=is_bot,
        is_deleted=is_deleted,
        status=status,
        last_online_date=last_online_date,
    )


def make_member(user, status=None):
    return SimpleNamespace(user=user, status=status)


def make_message(user, date):
    return SimpleNamespace(from_user=user, date=date)


class FakeDB:
    def __init__(self):
        self.leads = []
        self.sessions = []

    def add_lead(self, **kwargs):
        self.leads.append(kwargs)
        return True

    def log_parsing_session(self, target_chat, count):
        self.sessions.append((target_chat, count))


class FakeClient:
    def __init__(
        self,
        *,
        chat=None,
        join_result=None,
        join_error=None,
        members=None,
        admins=None,
        messages=None,
    ):
        self.chat = chat or SimpleNamespace(id=-100777, title="Test Chat")
        self.join_result = join_result or self.chat
        self.join_error = join_error
        self.members = list(members or [])
        self.admins = list(admins or [])
        self.messages = list(messages or [])
        self.join_calls = []
        self.get_chat_calls = []

    async def join_chat(self, target):
        self.join_calls.append(target)
        if self.join_error:
            raise self.join_error
        return self.join_result

    async def get_chat(self, target):
        self.get_chat_calls.append(target)
        return self.chat

    def get_chat_members(self, _chat_id, filter=None):
        source = self.admins if filter is not None else self.members

        async def _gen():
            for item in source:
                yield item

        return _gen()

    def get_chat_history(self, _chat_id):
        async def _gen():
            for message in self.messages:
                yield message

        return _gen()


class TestParsingEngineUnit(unittest.TestCase):
    def setUp(self):
        self.engine = ParsingEngine(FakeClient(), FakeDB())

    def test_normalize_target_input_cases(self):
        self.assertEqual(ParsingEngine._normalize_target_input("@name"), "@name")
        self.assertEqual(ParsingEngine._normalize_target_input("name"), "@name")
        self.assertEqual(ParsingEngine._normalize_target_input("12345"), "-10012345")
        self.assertEqual(
            ParsingEngine._normalize_target_input("https://t.me/c/12345/67"),
            "-10012345",
        )
        self.assertEqual(
            ParsingEngine._normalize_target_input("www.telegram.me/mychat"),
            "@mychat",
        )
        self.assertEqual(
            ParsingEngine._normalize_target_input("t.me/+AAAA"),
            "https://t.me/+AAAA",
        )

    def test_parse_date_bounds(self):
        date_from, date_to = ParsingEngine._parse_date_bounds(
            {"date_from_iso": "2026-01-01", "date_to_iso": "2026-01-03"}
        )
        self.assertEqual(date_from.isoformat(), "2026-01-01T00:00:00")
        self.assertEqual(date_to.isoformat(), "2026-01-03T23:59:59.999999")

        empty_from, empty_to = ParsingEngine._parse_date_bounds({})
        self.assertIsNone(empty_from)
        self.assertIsNone(empty_to)


class TestParsingEngineAsync(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_chat_invite_join_success(self):
        client = FakeClient()
        engine = ParsingEngine(client, FakeDB())

        chat, normalized = await engine._resolve_chat("t.me/+ABC")
        self.assertEqual(chat.id, -100777)
        self.assertEqual(normalized, "https://t.me/+ABC")
        self.assertEqual(client.join_calls, ["https://t.me/+ABC"])
        self.assertEqual(client.get_chat_calls, [])

    async def test_resolve_chat_invite_fallback_to_get_chat(self):
        client = FakeClient(join_error=RuntimeError("join failed"))
        engine = ParsingEngine(client, FakeDB())

        chat, normalized = await engine._resolve_chat("https://t.me/+ABC")
        self.assertEqual(chat.id, -100777)
        self.assertEqual(normalized, "https://t.me/+ABC")
        self.assertEqual(client.join_calls, ["https://t.me/+ABC"])
        self.assertEqual(client.get_chat_calls, ["https://t.me/+ABC"])

    async def test_basic_parsing_filters_members_and_logs_session(self):
        admin_status = getattr(enums.ChatMemberStatus, "ADMINISTRATOR", None)
        member_status = getattr(enums.ChatMemberStatus, "MEMBER", None)

        members = [
            make_member(make_user(1, username="admin"), status=admin_status),
            make_member(make_user(2, username="bot", is_bot=True), status=member_status),
            make_member(make_user(3, username="real"), status=member_status),
            make_member(make_user(4, username="deleted", is_deleted=True), status=member_status),
            make_member(None, status=member_status),
        ]

        db = FakeDB()
        client = FakeClient(members=members)
        engine = ParsingEngine(client, db)

        added = await engine.get_chat_members_basic(
            "https://t.me/mychat",
            {
                "only_active": False,
                "exclude_bots": True,
                "exclude_admins": True,
            },
        )

        self.assertEqual(added, 1)
        self.assertEqual(len(db.leads), 1)
        self.assertEqual(db.leads[0]["user_id"], 3)
        self.assertEqual(db.sessions, [("@mychat", 1)])

    async def test_deep_parsing_deduplicates_and_honors_window(self):
        now = datetime.now()
        recent_user = make_user(100, username="recent", status=getattr(enums.UserStatus, "RECENTLY", None))
        bot_user = make_user(101, username="bot", is_bot=True)
        old_user = make_user(102, username="old")

        messages = [
            make_message(recent_user, now),
            make_message(recent_user, now - timedelta(days=1)),
            make_message(bot_user, now - timedelta(days=1)),
            make_message(old_user, now - timedelta(days=10)),
            make_message(make_user(103, username="after_old"), now - timedelta(days=2)),
        ]

        db = FakeDB()
        client = FakeClient(messages=messages)
        engine = ParsingEngine(client, db)

        added = await engine.deep_parsing(
            "@mychat",
            7,
            {
                "only_active": False,
                "exclude_bots": True,
                "exclude_admins": False,
            },
        )

        self.assertEqual(added, 1)
        self.assertEqual(len(db.leads), 1)
        self.assertEqual(db.leads[0]["user_id"], 100)
        self.assertEqual(db.sessions, [("@mychat", 1)])


if __name__ == "__main__":
    unittest.main()
