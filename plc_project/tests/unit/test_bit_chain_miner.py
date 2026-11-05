"""Unit tests for Bit-Chain Sequencer Miner (Tab 3 Pattern B)."""

from __future__ import annotations

import pytest

from plc_engine.af.bit_chain_miner import BitChainMiner
from plc_engine.af.af_mapper import LegacyToAfMapper
from plc_engine.canvas_model import CanvasBlock, CanvasNetwork, CanvasState


def test_mine_classic_self_holding_chain() -> None:
    miner = BitChainMiner()
    code = """
    // Step sequencer using classic holding loops
    "M_Step1" := ("M_Init" AND "I_StartButton") OR ("M_Step1" AND NOT "M_Step2");
    "M_Step2" := ("M_Step1" AND "I_CylLoader_WorkPos") OR ("M_Step2" AND NOT "M_Step3");
    "M_Step3" := ("M_Step2" AND "I_PartDetect") OR ("M_Step3" AND NOT "M_Init");
    """
    chains = miner.mine_chains(code)
    assert len(chains) == 1
    chain = chains[0]
    # 4 variables: M_Init (Ready 1) -> M_Step1 (10) -> M_Step2 (20) -> M_Step3 (30)
    assert len(chain.step_variables) == 4
    assert '"M_Init"' in chain.step_variables
    assert '"M_Step1"' in chain.step_variables
    assert '"M_Step2"' in chain.step_variables
    assert '"M_Step3"' in chain.step_variables

    # Verify normalized Bosch steps
    steps = chain.normalized_steps
    assert len(steps) == 4
    # M_Init is Ready step 1
    assert steps[0].step_id == 1
    assert steps[0].transition_condition == '"I_StartButton"'
    assert steps[0].next_step_id == 10

    # M_Step1 is Auto step 10
    assert steps[1].step_id == 10
    assert steps[1].transition_condition == '"I_CylLoader_WorkPos"'
    assert steps[1].next_step_id == 20

    # M_Step2 is Auto step 20
    assert steps[2].step_id == 20
    assert steps[2].next_step_id == 30

    # M_Step3 is Auto step 30, looping back to Ready step 1
    assert steps[3].step_id == 30
    assert steps[3].next_step_id == 1


def test_mine_if_set_reset_chain() -> None:
    miner = BitChainMiner()
    code = """
    IF "M_Step1" AND "I_SensorA" THEN
        "M_Step2" := TRUE;
        "M_Step1" := FALSE;
    END_IF;
    IF "M_Step2" AND "I_SensorB" THEN
        "M_Step3" := TRUE;
        "M_Step2" := FALSE;
    END_IF;
    """
    chains = miner.mine_chains(code)
    assert len(chains) == 1
    assert len(chains[0].normalized_steps) >= 2


def test_end_to_end_af_mapper_recognizes_bit_chain() -> None:
    # Construct a legacy block using M-bits
    body = """
    "M_Step1" := ("M_Init" AND "I_Start") OR ("M_Step1" AND NOT "M_Step2");
    "M_Step2" := ("M_Step1" AND "I_CylWork") OR ("M_Step2" AND NOT "M_Step3");
    "M_Step3" := ("M_Step2" AND "I_Done") OR ("M_Step3" AND NOT "M_Init");
    """
    block = CanvasBlock(
        name="FC_Station1_AutoStep",
        block_type="FB",
        number=1001,
        language="SCL",
        scl_body=body,
    )
    canvas = CanvasState(
        project_name="TestMBitProject",
        blocks={"FC_Station1_AutoStep": block},
    )

    mapper = LegacyToAfMapper(canvas)
    analysis = mapper.analyze()

    assert analysis.degraded is False
    assert len(analysis.units[0].ems) == 1
    em = analysis.units[0].ems[0]
    assert len(em.steps) == 4
    assert em.steps[0].step_id == 1
    assert em.steps[0].next_step_id == 10
    assert em.steps[1].step_id == 10
    assert em.steps[1].next_step_id == 20
