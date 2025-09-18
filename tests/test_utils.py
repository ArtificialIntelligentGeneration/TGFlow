import unittest

from client_utils import normalize_recipient, is_supported_chat_type


class TestClientUtils(unittest.TestCase):
    def test_normalize_recipient_username(self):
        self.assertEqual(normalize_recipient('@user'), '@user')
        self.assertEqual(normalize_recipient('user'), '@user')
        self.assertEqual(normalize_recipient('https://t.me/user'), '@user')
        self.assertEqual(normalize_recipient('t.me/user'), '@user')

    def test_normalize_recipient_numeric(self):
        self.assertEqual(normalize_recipient('-100123'), '-100123')
        self.assertEqual(normalize_recipient('-100987654321'), '-100987654321')

    def test_normalize_recipient_preserve(self):
        self.assertEqual(normalize_recipient(' -100123 '), '-100123')

    def test_supported_chat_types(self):
        self.assertTrue(is_supported_chat_type('group'))
        self.assertTrue(is_supported_chat_type('supergroup'))
        self.assertTrue(is_supported_chat_type('channel'))
        self.assertFalse(is_supported_chat_type('private'))


if __name__ == '__main__':
    unittest.main()


