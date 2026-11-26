"""Regression coverage for Fernet ciphertext compatibility across upgrades."""

import unittest

from cryptography.fernet import Fernet


class FernetCompatibilityTests(unittest.TestCase):
    """Retain a synthetic known-answer token created by cryptography 43.0.1."""

    # Synthetic test material only. This key and token were generated under
    # cryptography 43.0.1 and do not encrypt any production credential.
    SYNTHETIC_KEY = b"4_gLiIl_bNWAWDM8KfBK7SeAFvPoxK_tRJSLaofJeyQ="
    SYNTHETIC_TOKEN = (
        b"gAAAAABrCDHoi9ByL9j7M9jNqEtQ9JfTQxIvEHeU7x7bKxl8XifekSvRHn88KuKGWzO"
        b"88KJpGL3xtcB_WvkakXj8Umdtqi7O_dzwe8ta2m7ryRsWIgxWXdK1EQxVSjfM_rgeRU"
        b"i8l32pOyzVATdpJOWAcQMlXOTlny_l_wRqWgYtZVMOBKKJ_Xs="
    )
    SYNTHETIC_PLAINTEXT = (
        b"SEC-1 synthetic Fernet compatibility plaintext; not a credential."
    )

    def test_synthetic_ciphertext_remains_decryptable(self):
        decrypted = Fernet(self.SYNTHETIC_KEY).decrypt(self.SYNTHETIC_TOKEN)
        self.assertEqual(decrypted, self.SYNTHETIC_PLAINTEXT)


if __name__ == "__main__":
    unittest.main()
