import os,pathlib,tempfile,threading,unittest
from reproloop.meta.gateway import read_owner_fifo

class IPCTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=pathlib.Path(self.tmp.name)/'key.pipe'

    def test_owner_only_fifo_no_persisted_data(self):
        os.mkfifo(self.path,0o600)
        def write():
            with self.path.open('wb',buffering=0) as file:
                file.write(b'synthetic-only-test-secret-123')
        thread=threading.Thread(target=write);thread.start()
        self.assertEqual(read_owner_fifo(self.path,2),'synthetic-only-test-secret-123')
        thread.join();self.assertFalse(self.path.exists())

    def test_regular_file_and_world_readable_fifo_rejected(self):
        self.path.write_text('not-a-key')
        with self.assertRaises(ValueError):read_owner_fifo(self.path,.1)
        self.path.unlink();os.mkfifo(self.path,0o666);self.path.chmod(0o666)
        with self.assertRaises(ValueError):read_owner_fifo(self.path,.1)

    def test_timeout_is_bounded_and_pipe_removed(self):
        os.mkfifo(self.path,0o600)
        with self.assertRaises(TimeoutError):read_owner_fifo(self.path,.05)
        self.assertFalse(self.path.exists())

    def test_symlink_rejected(self):
        other=self.path.parent/'other';os.mkfifo(other,0o600);self.path.symlink_to(other)
        with self.assertRaises(OSError):read_owner_fifo(self.path,.1)
