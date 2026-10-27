#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2026 The Basicswap developers
# Distributed under the MIT software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.

"""
basicswap]$ python tests/basicswap/extended/test_divi_electrum.py

The Divi regtest harness from test_divi.py, with node 1 using Divi in electrum
(light wallet) mode.  Node 0's divid must be IronDivi: it serves the Electrum
protocol to node 1.  Particl stays a full node on every client.

Node 1 is on the Divi side of each swap:
  * secret-hash, both directions, and a refund of node 1's own lock;
  * adaptor-sig PART->DIVI with node 1 locking DIVI (coin B), node 1
    receiving DIVI, and node 1 recovering its coin B lock.
"""

import logging
import os
import random
import unittest

import basicswap.config as cfg
from basicswap.basicswap import (
    BidStates,
    Coins,
    DebugTypes,
    SwapTypes,
)
from basicswap.basicswap_util import TxLockTypes
from basicswap.bin.run import startDaemon
from basicswap.util import COIN
from tests.basicswap.extended import test_divi
from tests.basicswap.test_xmr import test_delay_event as delay_event
from tests.basicswap.util.common import (
    make_rpc_func,
    read_json_api,
    wait_for_bid,
    wait_for_in_progress,
    wait_for_offer,
    waitForRPC,
)

DIVI_ELECTRUM_PORT = int(os.getenv("DIVI_ELECTRUM_PORT", "50101"))
ELECTRUM_NODE = 1


class Test(test_divi.Test):
    __test__ = True

    @classmethod
    def prepareExtraDataDir(cls, i):
        if not cls.restore_instance:
            test_divi.prepareDataDir(
                cfg.TEST_DATADIRS,
                i,
                "divi.conf",
                "divi_",
                base_p2p_port=test_divi.DIVI_BASE_PORT,
                base_rpc_port=test_divi.DIVI_BASE_RPC_PORT,
            )
        opts = [f"-electrum=127.0.0.1:{DIVI_ELECTRUM_PORT}"] if i == 0 else []
        cls.divi_daemons.append(
            startDaemon(
                os.path.join(cfg.TEST_DATADIRS, "divi_" + str(i)),
                test_divi.DIVI_BINDIR,
                test_divi.DIVID,
                opts=opts,
            )
        )
        logging.info("Started %s %d", test_divi.DIVID, cls.divi_daemons[-1].handle.pid)
        waitForRPC(
            make_rpc_func(i, base_rpc_port=test_divi.DIVI_BASE_RPC_PORT),
            delay_event,
            max_tries=30,
        )

    @classmethod
    def addCoinSettings(cls, settings, datadir, node_id):
        super().addCoinSettings(settings, datadir, node_id)
        if node_id != ELECTRUM_NODE:
            return
        settings["chainclients"]["divi"].update(
            {
                "connection_type": "electrum",
                "electrum_clearnet_servers": [f"127.0.0.1:{DIVI_ELECTRUM_PORT}"],
                "electrum_poll_interval": 2,
            }
        )

    def check_no_swaps_left(self):
        for port in (1800, 1801):
            js = read_json_api(port)
            assert js["num_swapping"] == 0 and js["num_watched_outputs"] == 0, js

    def test_e00_light_wallet(self):
        sc = self.swap_clients[ELECTRUM_NODE]
        ci = sc.ci(Coins.DIVI)
        assert ci.useBackend()
        assert not self.swap_clients[0].ci(Coins.DIVI).useBackend()

        # Node 1's deposit address comes from the BIP44 light wallet and is
        # a regtest P2PKH address.
        addr = read_json_api(1801, "wallets/divi/nextdepositaddr", {})
        assert addr[0] in ("x", "y"), addr
        assert sc.getWalletManager().getPrivateKey(Coins.DIVI, addr) is not None

        js = read_json_api(1801, "wallets/divi")
        assert float(js["balance"]) >= 1000.0, js
        # Headers come from the Electrum server and track the node.
        node_height = test_divi.diviCli("getblockcount")
        assert abs(ci.getChainHeight() - node_height) <= 2

    def test_e01_part_divi(self):
        # Node 1 participates with a DIVI lock and learns the secret from
        # node 0's redeem on the Divi chain.
        logging.info("---------- Test PART to DIVI, electrum node bids")
        swap_clients = self.swap_clients

        offer_id = swap_clients[0].postOffer(
            Coins.PART,
            Coins.DIVI,
            10 * COIN,
            2 * COIN,
            10 * COIN,
            SwapTypes.SELLER_FIRST,
            TxLockTypes.ABS_LOCK_TIME,
        )
        wait_for_offer(delay_event, swap_clients[1], offer_id)
        offer = swap_clients[1].getOffer(offer_id)
        bid_id = swap_clients[1].postBid(offer_id, offer.amount_from)

        wait_for_bid(delay_event, swap_clients[0], bid_id)
        swap_clients[0].acceptBid(bid_id)
        wait_for_in_progress(delay_event, swap_clients[1], bid_id, sent=True)

        wait_for_bid(
            delay_event, swap_clients[0], bid_id, BidStates.SWAP_COMPLETED, wait_for=240
        )
        wait_for_bid(
            delay_event,
            swap_clients[1],
            bid_id,
            BidStates.SWAP_COMPLETED,
            sent=True,
            wait_for=240,
        )
        self.check_no_swaps_left()

    def test_e02_divi_part(self):
        # Node 1 initiates with a DIVI lock.
        logging.info("---------- Test DIVI to PART, electrum node offers")
        swap_clients = self.swap_clients

        offer_id = swap_clients[1].postOffer(
            Coins.DIVI,
            Coins.PART,
            10 * COIN,
            0.5 * COIN,
            10 * COIN,
            SwapTypes.SELLER_FIRST,
            TxLockTypes.ABS_LOCK_TIME,
        )
        wait_for_offer(delay_event, swap_clients[0], offer_id)
        offer = swap_clients[0].getOffer(offer_id)
        bid_id = swap_clients[0].postBid(offer_id, offer.amount_from)

        wait_for_bid(delay_event, swap_clients[1], bid_id)
        swap_clients[1].acceptBid(bid_id)
        wait_for_in_progress(delay_event, swap_clients[0], bid_id, sent=True)

        wait_for_bid(
            delay_event,
            swap_clients[0],
            bid_id,
            BidStates.SWAP_COMPLETED,
            sent=True,
            wait_for=240,
        )
        wait_for_bid(
            delay_event, swap_clients[1], bid_id, BidStates.SWAP_COMPLETED, wait_for=240
        )
        self.check_no_swaps_left()

    def test_e03_divi_part_refund(self):
        # The bidder walks away after node 1 locks DIVI; node 1 refunds its
        # lock once the block height locktime passes.
        logging.info("---------- Test DIVI to PART refund, electrum node offers")
        swap_clients = self.swap_clients

        offer_id = swap_clients[1].postOffer(
            Coins.DIVI,
            Coins.PART,
            10 * COIN,
            0.5 * COIN,
            10 * COIN,
            SwapTypes.SELLER_FIRST,
            TxLockTypes.ABS_LOCK_BLOCKS,
            10,
        )
        wait_for_offer(delay_event, swap_clients[0], offer_id)
        offer = swap_clients[0].getOffer(offer_id)
        bid_id = swap_clients[0].postBid(offer_id, offer.amount_from)

        wait_for_bid(delay_event, swap_clients[1], bid_id)
        swap_clients[0].abandonBid(bid_id)
        swap_clients[1].acceptBid(bid_id)

        wait_for_bid(
            delay_event, swap_clients[1], bid_id, BidStates.SWAP_COMPLETED, wait_for=240
        )
        wait_for_bid(
            delay_event,
            swap_clients[0],
            bid_id,
            BidStates.BID_ABANDONED,
            sent=True,
            wait_for=60,
        )
        self.check_no_swaps_left()

    def run_part_divi_adaptor(self, offerer: int, bidder: int):
        swap_clients = self.swap_clients
        ci_from = swap_clients[offerer].ci(Coins.PART)
        ci_to = swap_clients[offerer].ci(Coins.DIVI)
        amt_swap = ci_from.make_int(random.uniform(0.1, 2.0), r=1)
        rate_swap = ci_to.make_int(random.uniform(2.0, 20.0), r=1)

        offer_id = swap_clients[offerer].postOffer(
            Coins.PART, Coins.DIVI, amt_swap, rate_swap, amt_swap, SwapTypes.XMR_SWAP
        )
        wait_for_offer(delay_event, swap_clients[bidder], offer_id)
        offer = swap_clients[bidder].getOffer(offer_id)
        bid_id = swap_clients[bidder].postBid(offer_id, offer.amount_from)

        wait_for_bid(delay_event, swap_clients[offerer], bid_id, BidStates.BID_RECEIVED)
        swap_clients[offerer].acceptBid(bid_id)

        wait_for_bid(
            delay_event,
            swap_clients[offerer],
            bid_id,
            BidStates.SWAP_COMPLETED,
            wait_for=240,
        )
        wait_for_bid(
            delay_event,
            swap_clients[bidder],
            bid_id,
            BidStates.SWAP_COMPLETED,
            sent=True,
            wait_for=240,
        )
        self.check_no_swaps_left()

    def test_e04_adaptor_part_divi_electrum_locks_b(self):
        # Node 1 is the follower: it funds the DIVI coin B lock.
        logging.info("---------- Test adaptor PART to DIVI, electrum node bids")
        self.run_part_divi_adaptor(offerer=0, bidder=1)

    def test_e05_adaptor_part_divi_electrum_redeems_b(self):
        # Node 1 is the leader: it spends the DIVI coin B lock.
        logging.info("---------- Test adaptor PART to DIVI, electrum node offers")
        self.run_part_divi_adaptor(offerer=1, bidder=0)

    def test_e06_adaptor_part_divi_recover_b_lock(self):
        # Node 1 locks DIVI, the swap fails, and node 1 takes its coin B
        # lock back.
        logging.info("---------- Test adaptor PART to DIVI, electrum node recovers B")
        swap_clients = self.swap_clients
        ci_from = swap_clients[0].ci(Coins.PART)
        ci_to = swap_clients[1].ci(Coins.DIVI)

        amt_swap = ci_from.make_int(random.uniform(0.1, 2.0), r=1)
        rate_swap = ci_to.make_int(random.uniform(2.0, 20.0), r=1)
        offer_id = swap_clients[0].postOffer(
            Coins.PART,
            Coins.DIVI,
            amt_swap,
            rate_swap,
            amt_swap,
            SwapTypes.XMR_SWAP,
            lock_type=TxLockTypes.SEQUENCE_LOCK_BLOCKS,
            lock_value=32,
        )
        wait_for_offer(delay_event, swap_clients[1], offer_id)
        offer = swap_clients[1].getOffer(offer_id)

        bid_id = swap_clients[1].postXmrBid(offer_id, offer.amount_from)
        wait_for_bid(delay_event, swap_clients[0], bid_id, BidStates.BID_RECEIVED)

        swap_clients[1].setBidDebugInd(bid_id, DebugTypes.CREATE_INVALID_COIN_B_LOCK)
        swap_clients[0].acceptXmrBid(bid_id)

        wait_for_bid(
            delay_event,
            swap_clients[0],
            bid_id,
            BidStates.XMR_SWAP_FAILED_REFUNDED,
            wait_for=240,
        )
        wait_for_bid(
            delay_event,
            swap_clients[1],
            bid_id,
            BidStates.XMR_SWAP_FAILED_REFUNDED,
            sent=True,
            wait_for=240,
        )


# Run only the electrum tests, not the inherited full-node suite.
for _name in dir(test_divi.Test):
    if _name.startswith("test_") and _name not in Test.__dict__:
        setattr(Test, _name, None)


if __name__ == "__main__":
    unittest.main()
