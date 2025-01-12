import json
import logging
import os
from pathlib import Path

import rlp
from dotenv import load_dotenv
from eth.vm.forks.shanghai.blocks import ShanghaiBlock
from web3 import Web3

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

load_dotenv()

TESTS_PATH = Path(
    "tests/integration/ef_tests/test_data/BlockchainTests/GeneralStateTests"
)
TEST_NAME = os.getenv("TEST_NAME")
if TEST_NAME is None:
    raise ValueError("Please set TEST_NAME")
TEST_PARENT_FOLDER = os.getenv("TEST_PARENT_FOLDER")
RPC_ENDPOINT = "http://127.0.0.1:8545"


def get_test_file():
    tests = [
        (content, str(file_path))
        for file_path in TESTS_PATH.glob("**/*.json")
        for name, content in json.load(open(file_path)).items()
        if TEST_NAME in name and content["network"] == "Shanghai"
    ]

    if len(tests) == 0:
        raise ValueError(f"Test {TEST_NAME} not found")

    if len(tests) > 1:
        if TEST_PARENT_FOLDER is None:
            raise ValueError(
                f"Test {TEST_NAME} is ambiguous, please set TEST_PARENT_FOLDER to test file folder"
            )

        test = [content for (content, path) in tests if TEST_PARENT_FOLDER in path]
        if len(test) == 0:
            raise ValueError(f"Test {TEST_NAME} not found")

        return test[0]

    else:
        return tests[0][0]


def connect_anvil():
    w3 = Web3(Web3.HTTPProvider(RPC_ENDPOINT, request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        raise Exception("Not connected to anvil endpoint")
    return w3


def set_pre_state(w3, data):
    for address, account in data["pre"].items():
        w3.provider.make_request("anvil_setCode", [address, account["code"]])
        w3.provider.make_request("anvil_setBalance", [address, account["balance"]])
        w3.provider.make_request("anvil_setNonce", [address, account["nonce"]])
        for k, v in account["storage"].items():
            w3.provider.make_request("anvil_setStorage", [address, k, v])


def get_block(data):
    try:
        block_rlp = data["blocks"][0]["rlp"]
        block = rlp.decode(bytes.fromhex(block_rlp[2:]), ShanghaiBlock)
    except Exception as e:
        raise Exception("Could not find block in test data") from e
    return block


def set_block(w3, data):
    block = get_block(data)
    w3.provider.make_request(
        "anvil_setCoinbase", [int.from_bytes(block.header.coinbase, "little")]
    )
    w3.provider.make_request(
        "anvil_setNextBlockBaseFeePerGas", [block.header.base_fee_per_gas]
    )


def send_transaction(w3, data):
    block = get_block(data)
    if len(block.transactions) == 0:
        raise ValueError("Could not find transaction in test data")
    tx_hash = w3.eth.send_raw_transaction(rlp.encode(block.transactions[0])).hex()
    return tx_hash


def check_post_state(w3, data):
    for address, account in data["postState"].items():
        address = Web3.to_checksum_address(address)
        try:
            assert w3.eth.get_balance(address) == int(account["balance"], 16)
            assert w3.eth.get_transaction_count(address) == int(account["nonce"], 16)
            assert w3.eth.get_code(address) == bytes.fromhex(account["code"][2:])
            for k, v in account["storage"].items():
                assert int.from_bytes(w3.eth.get_storage_at(address, k), "big") == int(
                    v, 16
                )
        except Exception as e:
            raise ValueError(f"Post state does not match for {address}, got {e}") from e
    logger.info("Post state is valid")


def main():
    test = get_test_file()
    provider = connect_anvil()

    # Set test state
    set_pre_state(provider, test)
    set_block(provider, test)

    # Send transaction
    tx_hash = send_transaction(provider, test)

    # Check post state
    check_post_state(provider, test)

    logger.info(f"Run `cast run {tx_hash} --debug` to debug transaction")


if __name__ == "__main__":
    main()
