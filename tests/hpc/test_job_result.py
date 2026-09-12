"""Recovering a value from job output that nobody controls."""

from agentic_base.hpc.job_result import ResultState, encode_result, parse_result

NOISE = """Lmod is loading modules
[rank1] warning: deprecated call
some library chatter
"""


def test_a_value_survives_surrounding_log_noise() -> None:
    output = NOISE + encode_result({"accuracy": 0.91}) + "\nteardown complete\n"

    result = parse_result(output)

    assert result.state is ResultState.OK
    assert result.value == {"accuracy": 0.91}


def test_no_block_at_all_is_absent_rather_than_corrupt() -> None:
    """The job returned nothing. That is a different situation from a lost result."""
    assert parse_result(NOISE).state is ResultState.ABSENT


def test_a_block_cut_off_by_a_killed_job_is_corrupt_rather_than_absent() -> None:
    """The result existed and was lost, which calls for a retry rather than a shrug."""
    truncated = NOISE + "###JOB_RESULT_START###\neyJhIjog"

    assert parse_result(truncated).state is ResultState.CORRUPT


def test_an_empty_block_is_corrupt() -> None:
    assert (
        parse_result("###JOB_RESULT_START###\n###JOB_RESULT_END###").state
        is ResultState.CORRUPT
    )


def test_a_payload_that_is_not_base64_is_corrupt() -> None:
    text = "###JOB_RESULT_START###\nnot base64 at all!\n###JOB_RESULT_END###"

    assert parse_result(text).state is ResultState.CORRUPT


def test_the_last_complete_block_wins_when_a_job_emits_progress() -> None:
    output = encode_result({"step": 1}) + "\nworking\n" + encode_result({"step": 2})

    assert parse_result(output).value == {"step": 2}


def test_a_value_containing_newlines_survives_because_the_payload_is_one_line() -> None:
    """This is the reason for base64. A multi-line payload is split by another rank's output."""
    value = {"log": "line one\nline two"}

    assert parse_result(encode_result(value)).value == value
