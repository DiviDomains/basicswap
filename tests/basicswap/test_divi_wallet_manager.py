#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2026 The Basicswap developers
# Distributed under the MIT software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.

"""Divi has no segwit: the light wallet derives P2PKH addresses on BIP44 paths."""

import logging
import unittest

from coincurve import PublicKey

from basicswap.chainparams import Coins
from basicswap.util.address import decodeAddress, pubkeyToAddress
from basicswap.util.crypto import hash160, sha256
from basicswap.util.extkey import ExtKeyPair
from basicswap.wallet_manager import WalletManager

SEED = bytes(range(32))


class FakeSwapClient:
    def __init__(self, chain: str):
        self.chain = chain


def make_wm(coin_type: Coins, chain: str) -> WalletManager:
    wm = WalletManager(FakeSwapClient(chain), logging.getLogger())
    ek = ExtKeyPair()
    ek.set_seed(SEED)
    purpose, coin_index = wm._purpose(coin_type), wm._coinIndex(coin_type)
    wm._root_extkeys[coin_type] = ek
    wm._external_chains[coin_type] = ek.derive_path(f"{purpose}h/{coin_index}h/0h/0")
    wm._internal_chains[coin_type] = ek.derive_path(f"{purpose}h/{coin_index}h/0h/1")
    return wm


def key_at(path: str) -> bytes:
    ek = ExtKeyPair()
    ek.set_seed(SEED)
    return ek.derive_path(path)._key


class TestDiviWalletManager(unittest.TestCase):
    def test_regtest_address(self):
        wm = make_wm(Coins.DIVI, "regtest")
        address, scripthash, pubkey = wm._deriveAddress(Coins.DIVI, 3)
        key = key_at("44h/1h/0h/0/3")
        self.assertEqual(pubkey, PublicKey.from_secret(key).format())
        self.assertEqual(address, pubkeyToAddress(139, pubkey))
        script = bytes.fromhex("76a914") + hash160(pubkey) + bytes.fromhex("88ac")
        self.assertEqual(scripthash, sha256(script)[::-1].hex())
        self.assertEqual(wm._computeScripthash(Coins.DIVI, address), scripthash)

    def test_mainnet_uses_coin_119(self):
        wm = make_wm(Coins.DIVI, "mainnet")
        address, _, pubkey = wm._deriveAddress(Coins.DIVI, 0, internal=True)
        self.assertEqual(
            pubkey, PublicKey.from_secret(key_at("44h/119h/0h/1/0")).format()
        )
        self.assertEqual(decodeAddress(address)[0], 30)
        self.assertTrue(address.startswith("D"))

    def test_paths(self):
        wm = make_wm(Coins.DIVI, "regtest")
        self.assertEqual(wm._pathType(Coins.DIVI), "bip44")
        self.assertEqual(wm._derivationPath(Coins.DIVI, True, 5), "m/44'/1'/0'/1/5")

    def test_scripthash_rejects_other_networks(self):
        wm = make_wm(Coins.DIVI, "regtest")
        mainnet_address, _, _ = make_wm(Coins.DIVI, "mainnet")._deriveAddress(
            Coins.DIVI, 0
        )
        self.assertEqual(wm._computeScripthash(Coins.DIVI, mainnet_address), "")
        self.assertEqual(wm._computeScripthash(Coins.DIVI, "not-an-address"), "")

    def test_btc_still_segwit(self):
        wm = make_wm(Coins.BTC, "regtest")
        address, scripthash, pubkey = wm._deriveAddress(Coins.BTC, 0)
        self.assertEqual(
            pubkey, PublicKey.from_secret(key_at("84h/0h/0h/0/0")).format()
        )
        self.assertTrue(address.startswith("bcrt1"))
        self.assertEqual(wm._pathType(Coins.BTC), "bip84")
        self.assertEqual(wm._computeScripthash(Coins.BTC, address), scripthash)


if __name__ == "__main__":
    unittest.main()
