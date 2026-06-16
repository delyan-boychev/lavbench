import os
import sys
import unittest

os.environ["SECRET_KEY"] = "test-key"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/0"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from cache_utils import cache_lock, log_dead_letter, get_redis_client, get_cached, set_cached, delete_cached


class TestCacheLock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = get_redis_client()
        if r:
            r.delete("lock:test:unit")

    def test_acquires_lock(self):
        with cache_lock("lock:test:unit", ttl=10) as got:
            self.assertTrue(got)

    def test_lock_releases_after_context(self):
        with cache_lock("lock:test:unit", ttl=10) as got:
            self.assertTrue(got)
        # After context exit, another acquisition should succeed
        with cache_lock("lock:test:unit", ttl=10) as got2:
            self.assertTrue(got2)

    def test_concurrent_lock_rejected(self):
        # First lock
        with cache_lock("lock:test:unit", ttl=10) as got1:
            self.assertTrue(got1)
            # Second attempt should fail while first holds
            r = get_redis_client()
            got2 = r.set("lock:test:unit", "test", nx=True, ex=10) if r else True
            self.assertFalse(got2)

    def test_uuid_ownership_prevents_cross_deletion(self):
        r = get_redis_client()
        if not r:
            self.skipTest("Redis unavailable")
        with cache_lock("lock:test:unit", ttl=10):
            # Simulate someone else setting the lock
            r.set("lock:test:unit", "evil-owner", ex=10)
        # Our finally should NOT have deleted "evil-owner" because owner mismatched
        val = r.get("lock:test:unit")
        self.assertIsNotNone(val)
        self.assertEqual(val.decode() if isinstance(val, bytes) else val, "evil-owner")
        r.delete("lock:test:unit")


class TestDeadLetterQueue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = get_redis_client()
        if r:
            r.delete("dead_letter_queue")

    def test_logs_entry(self):
        log_dead_letter(42, task_id=7, challenge_id=3, error="test error")
        r = get_redis_client()
        if not r:
            self.skipTest("Redis unavailable")
        entries = r.lrange("dead_letter_queue", 0, 0)
        self.assertEqual(len(entries), 1)
        import json
        data = json.loads(entries[0])
        self.assertEqual(data["submission_id"], 42)
        self.assertEqual(data["task_id"], 7)
        self.assertEqual(data["challenge_id"], 3)
        self.assertIn("test error", data["error"])
        r.delete("dead_letter_queue")

    def test_logs_without_error(self):
        log_dead_letter(1)
        r = get_redis_client()
        if not r:
            self.skipTest("Redis unavailable")
        entries = r.lrange("dead_letter_queue", 0, 0)
        self.assertEqual(len(entries), 1)
        r.delete("dead_letter_queue")

    def test_trims_to_1000(self):
        r = get_redis_client()
        if not r:
            self.skipTest("Redis unavailable")
        for i in range(1100):
            log_dead_letter(i)
        count = r.llen("dead_letter_queue")
        self.assertLessEqual(count, 1000)
        r.delete("dead_letter_queue")


class TestCacheOperations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = get_redis_client()
        if r:
            r.delete("test:cache:key")

    def test_set_and_get_cache(self):
        set_cached("test:cache:key", {"foo": "bar"}, timeout=30)
        result = get_cached("test:cache:key")
        self.assertIsNotNone(result)
        self.assertEqual(result["foo"], "bar")

    def test_get_returns_none_for_missing(self):
        result = get_cached("test:cache:nonexistent_key_xyz")
        self.assertIsNone(result)

    def test_delete_cache(self):
        set_cached("test:cache:key", {"x": 1}, timeout=30)
        self.assertTrue(get_cached("test:cache:key") is not None)
        delete_cached("test:cache:key")
        self.assertIsNone(get_cached("test:cache:key"))


if __name__ == '__main__':
    unittest.main()
