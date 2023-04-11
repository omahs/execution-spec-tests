"""
Test EIP-4844: Shard Blob Transactions (DATAHASH Opcode)
EIP: https://eips.ethereum.org/EIPS/eip-4844
"""
import itertools
from typing import Dict, List, Sequence

from ethereum_test_forks import Fork, ShardingFork
from ethereum_test_tools import (
    Account,
    BlobVersionedHashes,
    Block,
    BlockchainTest,
    CodeGasMeasure,
    Environment,
    StateTest,
    TestAddress,
    Transaction,
    Yul,
    compute_create2_address,
    compute_create_address,
    test_from,
    to_address,
    to_hash_bytes,
)
from ethereum_test_tools.vm.opcode import Opcodes as Op

REFERENCE_SPEC_GIT_PATH = "EIPS/eip-4844.md"
REFERENCE_SPEC_VERSION = "b33e063530f0a114635dd4f89d3cca90f8cac28f"

DATAHASH_GAS_COST = 3
MAX_BLOB_PER_BLOCK = 4

env = Environment(  # Global state test environment
    coinbase="0x2adc25665018aa1fe0e6bc666dac8fc2697ff9ba",
    difficulty=0x20000,
    gas_limit=300000000,
    number=1,
    timestamp=1000,
)


@test_from(fork=ShardingFork)
def test_datahash_opcode_contexts(_: Fork):
    """
    Test DATAHASH opcode called on different contexts.
    """
    datahash_verbatim = "verbatim_{}i_{}o".format(
        Op.DATAHASH.popped_stack_items, Op.DATAHASH.pushed_stack_items
    )

    datahash_sstore_bytecode = Yul(
        f"""
        {{
           let pos := calldataload(0)
           let end := calldataload(32)
           for {{}} lt(pos, end) {{ pos := add(pos, 1) }}
           {{
            let datahash := {datahash_verbatim}(hex"{Op.DATAHASH.hex()}", pos)
            sstore(pos, datahash)
           }}
           let datahash := {datahash_verbatim}(hex"{Op.DATAHASH.hex()}", end)
           sstore(end, datahash)
           return(0, 0)
        }}
        """
    )
    datahash_sstore_bytecode_address = to_address(0x100)

    datahash_return_bytecode = Yul(
        f"""
        {{
           let pos := calldataload(0)
           let datahash := {datahash_verbatim}(hex"{Op.DATAHASH.hex()}", pos)
           mstore(0, datahash)
           return(0, 32)
        }}
        """
    )
    datahash_return_bytecode_address = to_address(0x600)

    initcode_datahash_sstore_bytecode = Yul(
        f"""
        {{
           for {{ let pos := 0 }} lt(pos, 10) {{ pos := add(pos, 1) }}
           {{
            let datahash := {datahash_verbatim}(hex"{Op.DATAHASH.hex()}", pos)
            sstore(pos, datahash)
           }}
           return(0, 0)
        }}
        """
    )
    tx_created_contract_address = compute_create_address(TestAddress, 0)

    call_bytecode = Yul(
        """
        {
            calldatacopy(0, 0, calldatasize())
            pop(call(gas(), 0x100, 0, 0, calldatasize(), 0, 0))
        }
        """
    )
    call_bytecode_address = to_address(0x200)

    delegatecall_bytecode = Yul(
        """
        {
            calldatacopy(0, 0, calldatasize())
            pop(delegatecall(gas(), 0x100, 0, calldatasize(), 0, 0))
        }
        """
    )
    delegatecall_bytecode_address = to_address(0x300)

    callcode_bytecode = Yul(
        f"""
{{
    let pos := calldataload(0)
    let end := calldataload(32)
    for {{ }} lt(pos, end) {{ pos := add(pos, 1) }}
    {{
    mstore(0, pos)
    pop(callcode(gas(), {datahash_return_bytecode_address}, 0, 0, 32, 0, 32))
    let datahash := mload(0)
    sstore(pos, datahash)
    }}

    mstore(0, end)
    pop(callcode(gas(), {datahash_return_bytecode_address}, 0, 0, 32, 0, 32))
    let datahash := mload(0)
    sstore(end, datahash)
    return(0, 0)
}}
        """
    )
    callcode_bytecode_address = to_address(0x800)

    staticcall_bytecode = Yul(
        f"""
{{
    let pos := calldataload(0)
    let end := calldataload(32)
    for {{ }} lt(pos, end) {{ pos := add(pos, 1) }}
    {{
    mstore(0, pos)
    pop(staticcall(gas(), {datahash_return_bytecode_address}, 0, 32, 0, 32))
    let datahash := mload(0)
    sstore(pos, datahash)
    }}

    mstore(0, end)
    pop(staticcall(gas(), {datahash_return_bytecode_address}, 0, 32, 0, 32))
    let datahash := mload(0)
    sstore(end, datahash)
    return(0, 0)
}}
        """
    )
    staticcall_bytecode_address = to_address(0x700)

    create_bytecode = Yul(
        """
        {
            calldatacopy(0, 0, calldatasize())
            pop(create(0, 0, calldatasize()))
        }
        """
    )
    create_bytecode_address = to_address(0x400)
    create_opcode_created_contract = compute_create_address(
        create_bytecode_address, 0
    )

    create2_bytecode = Yul(
        """
        {
            calldatacopy(0, 0, calldatasize())
            pop(create2(0, 0, calldatasize(), 0))
        }
        """
    )
    create2_bytecode_address = to_address(0x500)
    create2_opcode_created_contract = compute_create2_address(
        create2_bytecode_address,
        0,
        initcode_datahash_sstore_bytecode.assemble(),
    )

    b_hashes: Sequence[bytes] = [
        to_hash_bytes(1 << x) for x in range(MAX_BLOB_PER_BLOCK)
    ]

    tags = [
        "at_top_level_call_stack",
        "max_value",
        "on_call",
        "on_delegatecall",
        "on_staticcall",
        "on_callcode",
        "on_initcode",
        "on_create",
        "on_create2",
        "tx_type_2",
        "tx_type_1",
        "tx_type_0",
    ]

    pre_states: List[Dict] = [
        {  # DATAHASH on top level of the call stack
            datahash_sstore_bytecode_address: Account(
                code=datahash_sstore_bytecode
            ),
        },
        {  # DATAHASH max value
            datahash_sstore_bytecode_address: Account(
                code=datahash_sstore_bytecode
            ),
        },
        {  # DATAHASH on CALL
            call_bytecode_address: Account(code=call_bytecode),
            datahash_sstore_bytecode_address: Account(
                code=datahash_sstore_bytecode
            ),
        },
        {  # DATAHASH on DELEGATECALL
            delegatecall_bytecode_address: Account(code=delegatecall_bytecode),
            datahash_sstore_bytecode_address: Account(
                code=datahash_sstore_bytecode
            ),
        },
        {  # DATAHASH on STATICCALL
            staticcall_bytecode_address: Account(code=staticcall_bytecode),
            datahash_return_bytecode_address: Account(
                code=datahash_return_bytecode
            ),
        },
        {  # DATAHASH on CALLCODE
            callcode_bytecode_address: Account(code=callcode_bytecode),
            datahash_return_bytecode_address: Account(
                code=datahash_return_bytecode
            ),
        },
        {},  # DATAHASH on INITCODE
        {  # DATAHASH on CREATE
            create_bytecode_address: Account(code=create_bytecode),
        },
        {  # DATAHASH on CREATE2
            create2_bytecode_address: Account(code=create2_bytecode),
        },
        {  # DATAHASH on type 2 tx
            datahash_sstore_bytecode_address: Account(
                code=datahash_sstore_bytecode
            ),
        },
        {  # DATAHASH on type 1 tx
            datahash_sstore_bytecode_address: Account(
                code=datahash_sstore_bytecode
            ),
        },
        {  # DATAHASH on type 0 tx
            datahash_sstore_bytecode_address: Account(
                code=datahash_sstore_bytecode
            ),
        },
    ]

    # Type 5 tx template
    tx_type_5 = Transaction(
        ty=5,
        data=to_hash_bytes(0),
        gas_limit=3000000,
        max_fee_per_gas=10,
        max_priority_fee_per_gas=10,
        max_fee_per_data_gas=10,
        access_list=[],
        blob_versioned_hashes=b_hashes,
    )

    txs = [
        tx_type_5.with_fields(  # DATAHASH on top level of the call stack
            to=datahash_sstore_bytecode_address,
            blob_versioned_hashes=b_hashes[:1],
        ),
        tx_type_5.with_fields(  # DATAHASH on max value
            data=to_hash_bytes(2**256 - 1) + to_hash_bytes(2**256 - 1),
            to=datahash_sstore_bytecode_address,
        ),
        tx_type_5.with_fields(  # DATAHASH on CALL
            data=to_hash_bytes(1) + to_hash_bytes(1),
            to=call_bytecode_address,
            blob_versioned_hashes=b_hashes[:2],
        ),
        tx_type_5.with_fields(  # DATAHASH on DELEGATECALL
            data=to_hash_bytes(0) + to_hash_bytes(3),
            to=delegatecall_bytecode_address,
        ),
        tx_type_5.with_fields(  # DATAHASH on STATICCALL
            data=to_hash_bytes(0) + to_hash_bytes(3),
            to=staticcall_bytecode_address,
        ),
        tx_type_5.with_fields(  # DATAHASH on CALLCODE
            data=to_hash_bytes(0) + to_hash_bytes(3),
            to=callcode_bytecode_address,
        ),
        tx_type_5.with_fields(  # DATAHASH on INITCODE
            data=initcode_datahash_sstore_bytecode, to=None
        ),
        tx_type_5.with_fields(  # DATAHASH on CREATE
            data=initcode_datahash_sstore_bytecode,
            to=create_bytecode_address,
        ),
        tx_type_5.with_fields(  # DATAHASH on CREATE2
            data=initcode_datahash_sstore_bytecode,
            to=create2_bytecode_address,
        ),
        Transaction(  # DATAHASH on type 2 tx
            ty=2,
            data=to_hash_bytes(0),
            to=datahash_sstore_bytecode_address,
            gas_limit=3000000,
            max_fee_per_gas=10,
            max_priority_fee_per_gas=10,
            access_list=[],
        ),
        Transaction(  # DATAHASH on type 1 tx
            ty=1,
            data=to_hash_bytes(0),
            to=datahash_sstore_bytecode_address,
            gas_limit=3000000,
            gas_price=10,
            access_list=[],
        ),
        Transaction(  # DATAHASH on type 0 tx
            ty=0,
            data=to_hash_bytes(0),
            to=datahash_sstore_bytecode_address,
            gas_limit=3000000,
            gas_price=10,
        ),
    ]

    post_states: List[Dict] = [
        {  # DATAHASH on top level of the call stack
            datahash_sstore_bytecode_address: Account(
                storage={0: b_hashes[0]}
            ),
        },
        {  # DATAHASH on max value
            datahash_sstore_bytecode_address: Account(storage={}),
        },
        {  # DATAHASH on CALL
            datahash_sstore_bytecode_address: Account(
                storage={1: b_hashes[1]}
            ),
        },
        {  # DATAHASH on DELEGATECALL
            delegatecall_bytecode_address: Account(
                storage={
                    k: v for (k, v) in zip(range(len(b_hashes)), b_hashes)
                }
            ),
        },
        {  # DATAHASH on STATICCALL
            staticcall_bytecode_address: Account(
                storage={
                    k: v for (k, v) in zip(range(len(b_hashes)), b_hashes)
                }
            ),
        },
        {  # DATAHASH on CALLCODE
            callcode_bytecode_address: Account(
                storage={
                    k: v for (k, v) in zip(range(len(b_hashes)), b_hashes)
                }
            ),
        },
        {  # DATAHASH on INITCODE
            tx_created_contract_address: Account(
                storage={
                    k: v for (k, v) in zip(range(len(b_hashes)), b_hashes)
                }
            ),
        },
        {  # DATAHASH on CREATE
            create_opcode_created_contract: Account(
                storage={
                    k: v for (k, v) in zip(range(len(b_hashes)), b_hashes)
                }
            ),
        },
        {  # DATAHASH on CREATE2
            create2_opcode_created_contract: Account(
                storage={
                    k: v for (k, v) in zip(range(len(b_hashes)), b_hashes)
                }
            ),
        },
        {  # DATAHASH on type 2 tx
            datahash_sstore_bytecode_address: Account(storage={0: 0}),
        },
        {  # DATAHASH on type 1 tx
            datahash_sstore_bytecode_address: Account(storage={0: 0}),
        },
        {  # DATAHASH on type 0 tx
            datahash_sstore_bytecode_address: Account(storage={0: 0}),
        },
    ]

    for pre, post, tag, tx in zip(pre_states, post_states, tags, txs):
        pre[TestAddress] = Account(balance=1000000000000000000000)
        yield StateTest(
            env=env,
            pre=pre,
            post=post,
            txs=[tx],
            tag=tag,
        )


@test_from(fork=ShardingFork)
def test_datahash_gas_cost(_: Fork):
    """
    Test DATAHASH opcode gas cost using a variety of indexes.
    """
    pre = {
        TestAddress: Account(balance=1000000000000000000000),
    }
    # Transaction template
    tx = Transaction(
        data=to_hash_bytes(0),
        gas_limit=3000000,
        max_fee_per_gas=10,
        max_fee_per_data_gas=10,
    )
    post = {}

    # Declare datahash indexes: zero, max & random values
    datahash_index_measures: List[int] = [
        0x00,
        2**256 - 1,
        0x30A9B2A6C3F3F0675B768D49B5F5DC5B5D988F88D55766247BA9E40B125F16BB,
        0x4FA4D4CDE4AA01E57FB2C880D1D9C778C33BDF85E48EF4C4D4B4DE51ABCCF4ED,
        0x7871C9B8A0C72D38F5E5B5D08E5CB5CE5E23FB1BC5D75F9C29F7B94DF0BCEEB7,
        0xA12C8B6A8B11410C7D98D790E1098F1ED6D93CB7A64711481AAAB1848E13212F,
    ]

    gas_measures_code = [
        CodeGasMeasure(
            code=Op.PUSH32(index) + Op.DATAHASH,
            overhead_cost=3,
            extra_stack_items=1,
        )
        for index in datahash_index_measures
    ]

    txs_type_0, txs_type_1, txs_type_2, txs_type_5 = ([] for _ in range(4))
    for i, code in enumerate(gas_measures_code):
        address = to_address(0x100 + i * 0x100)
        pre[address] = Account(code=code)
        txs_type_0.append(
            tx.with_fields(ty=0, to=address, nonce=i, gas_price=10)
        )
        txs_type_1.append(
            tx.with_fields(ty=1, to=address, nonce=i, gas_price=10)
        )
        txs_type_2.append(
            tx.with_fields(
                ty=2,
                to=address,
                nonce=i,
                max_priority_fee_per_gas=10,
                blob_versioned_hashes=[
                    BlobVersionedHashes[i % MAX_BLOB_PER_BLOCK]
                ],
            )
        )
        txs_type_5.append(
            tx.with_fields(
                ty=5,
                to=address,
                nonce=i,
                max_priority_fee_per_gas=10,
                blob_versioned_hashes=[
                    BlobVersionedHashes[i % MAX_BLOB_PER_BLOCK]
                ],
            )
        )
        post[address] = Account(storage={0: DATAHASH_GAS_COST})

    # DATAHASH gas cost on tx type 0, 1 & 2
    for i, txs in enumerate([txs_type_0, txs_type_1, txs_type_2]):
        yield StateTest(
            env=env, pre=pre, post=post, txs=txs, tag=f"tx_type_{i}"
        )

    # DATAHASH gas cost on tx type 5
    total_blocks = (
        len(txs_type_5) + MAX_BLOB_PER_BLOCK - 1
    ) // MAX_BLOB_PER_BLOCK
    blocks = [
        Block(
            txs=txs_type_5[
                i * MAX_BLOB_PER_BLOCK : (i + 1) * MAX_BLOB_PER_BLOCK
            ]
        )
        for i in range(total_blocks)
    ]

    yield BlockchainTest(pre=pre, post=post, blocks=blocks, tag="tx_type_5")


@test_from(fork=ShardingFork)
def test_datahash_blob_versioned_hash(_: Fork):
    """
    Tests that the `DATAHASH` opcode returns the correct versioned hash for
    various valid index scenarios.
    """
    TOTAL_BLOCKS = 10

    pre = {
        TestAddress: Account(balance=10000000000000000000000),
    }
    post = {}
    blocks = []

    # Create an arbitrary repeated list of blob hashes
    # with length MAX_BLOB_PER_BLOCK * TOTAL_BLOCKS
    blob_hashes = list(
        itertools.islice(
            itertools.cycle(BlobVersionedHashes),
            MAX_BLOB_PER_BLOCK * TOTAL_BLOCKS,
        )
    )

    # `DATAHASH` sstore template helper
    def datahash_sstore(index: int):
        return Op.PUSH1(index) + Op.DATAHASH + Op.PUSH1(index) + Op.SSTORE()

    # `DATAHASH` on valid indexes
    datahash_single_valid_calls = b"".join(
        datahash_sstore(i) for i in range(MAX_BLOB_PER_BLOCK)
    )
    pre_single_valid_calls = pre

    # `DATAHASH` on valid index repeated:
    # DATAHASH(i), DATAHASH(i), ...
    datahash_repeated_valid_calls = b"".join(
        b"".join([datahash_sstore(i) for _ in range(10)])
        for i in range(MAX_BLOB_PER_BLOCK)
    )
    pre_datahash_repeated_valid_calls = pre

    # `DATAHASH` on valid/invalid/valid:
    # DATAHASH(i), DATAHASH(MAX_BLOB_PER_BLOCK), DATAHASH(i)
    datahash_valid_invalid_calls = b"".join(
        datahash_sstore(i)
        + datahash_sstore(MAX_BLOB_PER_BLOCK)
        + datahash_sstore(i)
        for i in range(MAX_BLOB_PER_BLOCK)
    )
    pre_datahash_valid_invalid_calls = pre

    # `DATAHASH` on different valid indexes repeated:
    # DATAHASH(i), DATAHASH(i+1), DATAHASH(i)
    datahash_varied_valid_calls = b"".join(
        datahash_sstore(i) + datahash_sstore(i + 1) + datahash_sstore(i)
        for i in range(MAX_BLOB_PER_BLOCK - 1)
    )
    pre_datahash_varied_valid_calls = pre

    for i in range(TOTAL_BLOCKS):
        address = to_address(0x100 + i * 0x100)
        pre_single_valid_calls[address] = Account(
            code=datahash_single_valid_calls
        )
        pre_datahash_repeated_valid_calls[address] = Account(
            code=datahash_repeated_valid_calls
        )
        pre_datahash_valid_invalid_calls[address] = Account(
            code=datahash_valid_invalid_calls
        )
        pre_datahash_varied_valid_calls[address] = Account(
            code=datahash_varied_valid_calls
        )
        blocks.append(
            Block(
                txs=[  # Create tx with max blobs per block
                    Transaction(
                        ty=5,
                        nonce=i,
                        data=to_hash_bytes(0),
                        to=address,
                        gas_limit=3000000,
                        max_fee_per_gas=10,
                        max_priority_fee_per_gas=10,
                        max_fee_per_data_gas=10,
                        access_list=[],
                        blob_versioned_hashes=blob_hashes[
                            (i * MAX_BLOB_PER_BLOCK) : (i + 1)
                            * MAX_BLOB_PER_BLOCK
                        ],
                    )
                ]
            )
        )
        post[address] = Account(
            storage={
                index: blob_hashes[i * MAX_BLOB_PER_BLOCK + index]
                for index in range(MAX_BLOB_PER_BLOCK)
            }
        )

    yield BlockchainTest(
        pre=pre_single_valid_calls,
        post=post,
        blocks=blocks,
        tag="valid_calls",
    )

    yield BlockchainTest(
        pre=pre_datahash_repeated_valid_calls,
        post=post,
        blocks=blocks,
        tag="repeated_calls",
    )

    yield BlockchainTest(
        pre=pre_datahash_valid_invalid_calls,
        post=post,
        blocks=blocks,
        tag="valid_invalid_calls",
    )

    yield BlockchainTest(
        pre=pre_datahash_varied_valid_calls,
        post=post,
        blocks=blocks,
        tag="varied_valid_calls",
    )


@test_from(fork=ShardingFork)
def test_datahash_invalid_blob_index(_: Fork):
    """
    Tests that the `DATAHASH` opcode returns a zeroed bytes32 value
    for invalid indexes.
    """
    INVALID_DEPTH_FACTOR = 5
    TOTAL_BLOCKS = 10

    pre = {
        TestAddress: Account(balance=10000000000000000000000),
    }
    blocks = []
    post = {}

    # `DATAHASH` on invalid indexes: -ve invalid -> valid -> +ve invalid:
    datahash_invalid_calls = b"".join(
        Op.PUSH1(i) + Op.DATAHASH + Op.PUSH1(i) + Op.SSTORE()
        for i in range(
            -INVALID_DEPTH_FACTOR, MAX_BLOB_PER_BLOCK + INVALID_DEPTH_FACTOR
        )
    )

    for i in range(TOTAL_BLOCKS):
        address = to_address(0x100 + i * 0x100)
        pre[address] = Account(code=datahash_invalid_calls)
        blob_per_block = i % MAX_BLOB_PER_BLOCK
        blob_hashes = [
            BlobVersionedHashes[blob] for blob in range(blob_per_block)
        ]
        blocks.append(
            Block(
                txs=[
                    Transaction(
                        ty=5,
                        nonce=i,
                        data=to_hash_bytes(0),
                        to=address,
                        gas_limit=3000000,
                        max_fee_per_gas=10,
                        max_priority_fee_per_gas=10,
                        max_fee_per_data_gas=10,
                        access_list=[],
                        blob_versioned_hashes=blob_hashes,
                    )
                ]
            )
        )
        post[address] = Account(
            storage={
                index: 0
                if index < 0 or index >= blob_per_block
                else blob_hashes[index]
                for index in range(
                    -INVALID_DEPTH_FACTOR,
                    blob_per_block + INVALID_DEPTH_FACTOR,
                )
            }
        )

    yield BlockchainTest(
        pre=pre,
        post=post,
        blocks=blocks,
    )


@test_from(fork=ShardingFork)
def test_datahash_multiple_txs_in_block(_: Fork):
    """
    Tests that the `DATAHASH` opcode returns the appropriate values
    when there is more than one blob tx type within a block.
    """
    datahash_valid_call = b"".join(
        [
            Op.PUSH1(i) + Op.DATAHASH + Op.PUSH1(i) + Op.SSTORE()
            for i in range(MAX_BLOB_PER_BLOCK)
        ]
    )

    pre = {
        TestAddress: Account(balance=10000000000000000000000),
        to_address(0x100): Account(
            code=datahash_valid_call,
        ),
        to_address(0x200): Account(
            code=datahash_valid_call,
        ),
    }

    tx = Transaction(
        data=to_hash_bytes(0),
        gas_limit=3000000,
        max_fee_per_gas=10,
        max_priority_fee_per_gas=10,
        max_fee_per_data_gas=10,
        access_list=[],
        blob_versioned_hashes=BlobVersionedHashes[0:MAX_BLOB_PER_BLOCK],
    )

    blocks = [
        Block(
            txs=[
                tx.with_fields(ty=5, nonce=0, to=to_address(0x100)),
                tx.with_fields(ty=2, nonce=1, to=to_address(0x100)),
            ]
        ),
        Block(
            txs=[
                tx.with_fields(ty=2, nonce=2, to=to_address(0x200)),
                tx.with_fields(ty=5, nonce=3, to=to_address(0x200)),
            ]
        ),
    ]

    post = {
        to_address(0x100): Account(
            storage={i: 0 for i in range(MAX_BLOB_PER_BLOCK)}
        ),
        to_address(0x200): Account(
            storage={
                i: BlobVersionedHashes[i] for i in range(MAX_BLOB_PER_BLOCK)
            }
        ),
    }

    yield BlockchainTest(
        pre=pre,
        post=post,
        blocks=blocks,
    )
