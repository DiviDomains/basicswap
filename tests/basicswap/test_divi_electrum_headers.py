#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2026 The Basicswap developers
# Distributed under the MIT software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.

"""Divi headers in the Electrum header chain.

Divi headers are padded to 112 bytes by the IronDivi Electrum server.  A
version 4+ header hashes with sha256d over the 112 bytes; an older one hashes
with Quark, which BasicSwap does not implement, so it is trusted.
"""

import unittest

from basicswap.interface.divi.divi import (
    DIVI_GENESIS,
    DIVI_HEADER_SIZE,
    DIVIInterface,
    divi_hash_raw_header,
)
from basicswap.interface.electrum_blockchain import (
    HeaderSync,
    hash_encode,
    serialize_header,
    sha256d,
)
from tests.basicswap.test_electrum_blockchain import StubLog, make_manager


def divi_net(network: str = "regtest"):
    ci = DIVIInterface.__new__(DIVIInterface)
    ci._network = network
    return ci._electrumHeaderNet()


def legacy_genesis() -> dict:
    # Stands in for a Quark-hashed genesis: version 1, zero prev-hash.
    return {
        "version": 1,
        "prev_block_hash": "00" * 32,
        "merkle_root": "11" * 32,
        "timestamp": 1000000,
        "bits": 0x207FFFFF,
        "nonce": 7,
        "block_height": 0,
        "extra": "00" * 32,
    }


def pos_chain(net, prev: dict | None, start: int, count: int, tag: int = 0):
    headers = []
    prev_hash = net.GENESIS if start == 1 else net.hash_header(prev)
    timestamp = prev["timestamp"] if prev else 1000000
    for height in range(start, start + count):
        timestamp += 60
        header = {
            "version": 4,
            "prev_block_hash": prev_hash,
            "merkle_root": f"{tag:064x}",
            "timestamp": timestamp,
            "bits": 0x207FFFFF,
            "nonce": 0,
            "block_height": height,
            "extra": f"{height:064x}",
        }
        headers.append(header)
        prev_hash = net.hash_header(header)
    return headers


class DiviServer:
    def __init__(self, headers: list):
        self.headers = headers

    def call(self, method, params):
        if method == "blockchain.block.header":
            return serialize_header(self.headers[params[0]]).hex()
        if method == "blockchain.block.headers":
            selected = self.headers[params[0] : params[0] + params[1]]
            return {
                "hex": b"".join(serialize_header(h) for h in selected).hex(),
                "count": len(selected),
                "max": 2016,
            }
        raise RuntimeError(f"unexpected call {method}")


class TestDiviHeaderHash(unittest.TestCase):
    def test_v4_is_sha256d_over_112_bytes(self):
        net = divi_net()
        header = pos_chain(net, legacy_genesis(), 1, 1)[0]
        raw = serialize_header(header)
        self.assertEqual(len(raw), DIVI_HEADER_SIZE)
        self.assertEqual(divi_hash_raw_header(raw), hash_encode(sha256d(raw)))
        # The accumulator checkpoint is part of the hash.
        self.assertNotEqual(divi_hash_raw_header(raw), hash_encode(sha256d(raw[:80])))

    def test_legacy_is_not_hashed(self):
        raw = serialize_header(legacy_genesis())
        self.assertEqual(len(raw), DIVI_HEADER_SIZE)
        self.assertIsNone(divi_hash_raw_header(raw))

    def test_round_trip_keeps_accumulator(self):
        net = divi_net()
        header = pos_chain(net, legacy_genesis(), 1, 1)[0]
        raw = serialize_header(header)
        self.assertEqual(serialize_header(net.deserialize_header(raw, 1)), raw)

    def test_networks(self):
        for network, genesis in DIVI_GENESIS.items():
            net = divi_net(network)
            self.assertEqual(net.GENESIS, genesis)
            self.assertEqual(net.HEADER_SIZE, DIVI_HEADER_SIZE)
            self.assertTrue(net.SKIP_POW)


class TestDiviHeaderSync(unittest.TestCase):
    def setUp(self):
        self.net = divi_net()
        self.bc_mgr = make_manager(self.net)
        self.main = [legacy_genesis()] + pos_chain(self.net, legacy_genesis(), 1, 30)

    def sync_to(self, server_headers: list):
        sync = HeaderSync(self.bc_mgr, DiviServer(server_headers), StubLog())
        tip = len(server_headers) - 1
        sync.process_header_at_tip(tip, server_headers[tip])

    def test_syncs_from_legacy_genesis(self):
        self.sync_to(self.main)
        best = self.bc_mgr.get_best_chain()
        self.assertEqual(best.height(), 30)
        self.assertEqual(
            self.net.hash_header(best.header_at_tip()),
            self.net.hash_header(self.main[-1]),
        )

    def test_longer_fork_becomes_best(self):
        self.sync_to(self.main)
        fork = self.main[:20] + pos_chain(self.net, self.main[19], 20, 15, tag=7)
        self.sync_to(fork)
        best = self.bc_mgr.get_best_chain()
        self.assertEqual(best.height(), 34)
        self.assertEqual(best.get_hash(20), self.net.hash_header(fork[20]))

    def test_height_one_must_link_to_genesis(self):
        other = divi_net()
        other.GENESIS = "22" * 32
        wrong = [legacy_genesis()] + pos_chain(other, legacy_genesis(), 1, 30)
        with self.assertRaisesRegex(Exception, "bad header"):
            self.sync_to(wrong)
        best = self.bc_mgr.get_best_chain()
        self.assertLess(best.height(), 1)

    def test_broken_link_refused(self):
        broken = [dict(h) for h in self.main]
        broken[15]["extra"] = "ff" * 32  # changes the hash of block 15
        with self.assertRaisesRegex(Exception, "bad header"):
            self.sync_to(broken)
        self.assertLess(self.bc_mgr.get_best_chain().height(), 16)


if __name__ == "__main__":
    unittest.main()
