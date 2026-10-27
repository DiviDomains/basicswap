#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2026 The Basicswap developers
# Distributed under the MIT software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.

"""Divi light wallet: legacy P2PKH signing, sizing and fees."""

import unittest
from unittest.mock import MagicMock

from coincurve import PrivateKey

from basicswap.contrib.test_framework.messages import (
    COutPoint,
    CTransaction,
    CTxIn,
    CTxOut,
)
from basicswap.contrib.test_framework.script import (
    CScript,
    LegacySignatureHash,
    SIGHASH_ALL,
)
from basicswap.interface.divi.divi import DIVIInterface
from basicswap.util.crypto import hash160
from tests.basicswap.util.common import REQUIRED_SETTINGS

KEY = bytes.fromhex("11" * 32)
PREV_TXID = "aa" * 32


def make_ci(fee_settings=None) -> DIVIInterface:
    settings = dict(REQUIRED_SETTINGS)
    settings.update({"rpcport": 0, "rpcauth": "none", "connection_type": "electrum"})
    ci = DIVIInterface(settings, "regtest")
    ci._log = MagicMock()
    ci._sc = MagicMock()
    ci._sc.getChainClientSettings.return_value = fee_settings or {}
    # Stands in for the Electrum server, so useBackend() holds
    ci._backend = MagicMock()
    return ci


def spend_tx(ci, n_inputs: int = 1) -> CTransaction:
    tx = CTransaction()
    tx.nVersion = ci.txVersion()
    for i in range(n_inputs):
        tx.vin.append(CTxIn(COutPoint(int(PREV_TXID, 16), i)))
    tx.vout.append(CTxOut(90000, ci.getScriptForPubkeyHash(b"\x22" * 20)))
    return tx


class TestDiviLegacySigning(unittest.TestCase):
    def setUp(self):
        self.ci = make_ci()
        self.pubkey = PrivateKey(KEY).public_key.format()
        self.script_code = self.ci.getScriptForPubkeyHash(hash160(self.pubkey))

    def test_sign_uses_legacy_sighash(self):
        tx = spend_tx(self.ci, 2)
        tx_bytes = tx.serialize()
        sig = self.ci.signTx(KEY, tx_bytes, 1, self.script_code, 100000)
        self.assertEqual(sig[-1], SIGHASH_ALL)
        self.assertLess(len(sig), 72)  # low R
        self.assertTrue(
            self.ci.verifyTxSig(tx_bytes, sig, self.pubkey, 1, self.script_code, 0)
        )
        # The digest commits to the input index.
        self.assertFalse(
            self.ci.verifyTxSig(tx_bytes, sig, self.pubkey, 0, self.script_code, 0)
        )
        sig_hash = LegacySignatureHash(self.script_code, tx, 1, SIGHASH_ALL)[0]
        self.assertTrue(
            PrivateKey(KEY).public_key.verify(sig[:-1], sig_hash, hasher=None)
        )

    def test_verify_rejects_other_hashtypes(self):
        tx_bytes = spend_tx(self.ci).serialize()
        sig = self.ci.signTx(KEY, tx_bytes, 0, self.script_code, 0)
        self.assertFalse(
            self.ci.verifyTxSig(
                tx_bytes, sig[:-1] + b"\x03", self.pubkey, 0, self.script_code, 0
            )
        )
        self.assertFalse(
            self.ci.verifyTxSig(tx_bytes, b"", self.pubkey, 0, self.script_code, 0)
        )

    def test_sign_with_key_fills_script_sig(self):
        tx_bytes = spend_tx(self.ci).serialize()
        signed = self.ci.signTxWithKey(tx_bytes, KEY, 100000)
        tx = self.ci.loadTx(signed)
        self.assertFalse(tx.wit.vtxinwit)
        # Legacy serialisation: no segwit marker after the version.
        self.assertNotEqual(signed[4:6], b"\x00\x01")
        sig, pubkey = list(CScript(tx.vin[0].scriptSig))
        self.assertEqual(pubkey, self.pubkey)
        self.assertTrue(
            self.ci.verifyTxSig(tx_bytes, sig, pubkey, 0, self.script_code, 0)
        )

    def test_sign_with_wallet_signs_each_input(self):
        address = self.ci.pubkey_to_address(self.pubkey)
        prev = CTransaction()
        prev.vout = [CTxOut(50000, self.script_code) for _ in range(2)]

        wm = MagicMock()
        wm.getPrivateKey.return_value = KEY
        backend = MagicMock()
        backend.getTransactionBatch.return_value = {}
        backend.getTransactionBatchRaw.return_value = {
            PREV_TXID: prev.serialize().hex()
        }
        self.ci._backend = backend
        self.ci.getWalletManager = lambda: wm
        self.ci.getBackend = lambda: backend

        tx_bytes = spend_tx(self.ci, 2).serialize()
        signed = self.ci.loadTx(self.ci.signTxWithWallet(tx_bytes))
        wm.getPrivateKey.assert_called_with(self.ci.coin_type(), address)
        for n in range(2):
            sig, pubkey = list(CScript(signed.vin[n].scriptSig))
            self.assertTrue(
                self.ci.verifyTxSig(tx_bytes, sig, pubkey, n, self.script_code, 0)
            )


class TestDiviElectrumSizing(unittest.TestCase):
    def test_input_size_is_p2pkh(self):
        ci = make_ci()
        self.assertEqual(ci._electrumInputVSize(), 148)
        self.assertEqual(ci._electrumSigBytes(3), (321, 0))
        # Unsigned input plus the scriptSig estimate is a signed P2PKH input.
        tx = spend_tx(ci, 3)
        sig_bytes, wit_bytes = ci._electrumSigBytes(3)
        self.assertEqual(
            ci.getTxVSize(tx, sig_bytes, wit_bytes),
            10 + 3 * ci.TX_P2PKH_INPUT_BYTES + 34,
        )

    def test_fund_pays_legacy_fee(self):
        ci = make_ci()
        pubkey = PrivateKey(KEY).public_key.format()
        addr = ci.pubkey_to_address(pubkey)
        sh = ci.addressToScripthash(addr)
        utxos = [
            {"txid": "aa" * 32, "vout": 0, "value": 60000, "confirmations": 3},
            {"txid": "bb" * 32, "vout": 0, "value": 60000, "confirmations": 3},
        ]

        class FakeBackend:
            def getBatchUnspent(self, scripthashes, min_confirmations=0):
                return {sh: utxos}

        wm = MagicMock()
        wm.getFundedAddresses.return_value = {addr: sh}
        wm.getSignableAddresses.return_value = {addr: sh}
        wm.getInternalAddresses.return_value = set()
        wm.getNewInternalAddress.return_value = addr
        wm.isUTXOLocked.return_value = False
        ci._backend = FakeBackend()
        ci.getWalletManager = lambda: wm

        tx = CTransaction()
        tx.nVersion = ci.txVersion()
        tx.vout.append(CTxOut(100000, ci.getScriptForPubkeyHash(b"\x22" * 20)))
        funded = ci.loadTx(ci._fundTxElectrum(tx.serialize(), 10000))
        self.assertEqual(len(funded.vin), 2)
        self.assertEqual(len(funded.vout), 2)
        fee = 120000 - sum(out.nValue for out in funded.vout)
        size = 10 + 2 * 148 + 2 * 34
        # 10000 sat/kB, so about 10 sat per byte of the signed size.
        self.assertGreaterEqual(fee, size * 10 - 10)
        self.assertLessEqual(fee, size * 10 + 10)


class TestDiviDescribeTx(unittest.TestCase):
    def test_base58_addresses(self):
        ci = make_ci()
        script = CScript([b"\x01" * 33])
        tx = spend_tx(ci)
        tx.vout.append(CTxOut(5000, ci.getScriptDest(script)))
        txjs = ci.decodeRawTransaction(tx.serialize().hex())
        self.assertEqual(txjs["txid"], tx.rehash())
        self.assertEqual(txjs["vin"][0]["txid"], PREV_TXID)
        self.assertEqual(
            txjs["vout"][0]["scriptPubKey"]["address"],
            ci.pkh_to_address(b"\x22" * 20),
        )
        self.assertEqual(
            txjs["vout"][1]["scriptPubKey"]["address"], ci.encode_p2sh(script)
        )


class TestDiviFeeRate(unittest.TestCase):
    def test_electrum_fallback_is_raised_to_relay_fee(self):
        ci = make_ci()
        ci._backend = MagicMock()
        ci._backend.estimateFee.side_effect = RuntimeError("no estimate")
        fee_rate, src = ci.get_fee_rate()
        self.assertEqual(fee_rate, 0.0001)
        self.assertIn("min relay fee", src)

    def test_higher_estimate_is_kept(self):
        ci = make_ci()
        ci._backend = MagicMock()
        ci._backend.estimateFee.return_value = 50  # sat/vB
        self.assertEqual(ci.get_fee_rate(), (0.0005, "electrum"))

    def test_override_below_floor_is_raised(self):
        ci = make_ci({"override_feerate": 0.00002})
        self.assertEqual(ci.get_fee_rate()[0], 0.0001)


class TestDiviNoAccountKey(unittest.TestCase):
    def test_no_export(self):
        ci = make_ci()
        self.assertFalse(ci.canExportToElectrum())
        with self.assertRaises(ValueError):
            ci.getAccountKey(KEY, 0x045F18BC)


if __name__ == "__main__":
    unittest.main()
