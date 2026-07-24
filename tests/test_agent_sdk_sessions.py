from amosclaud_agent_sdk.session_mutations import truncate_messages, update_metadata
from amosclaud_agent_sdk.session_store import SessionStore
from amosclaud_agent_sdk.session_store_validation import validate_session_document
from amosclaud_agent_sdk.session_summary import summarize_session
from amosclaud_agent_sdk.sessions import create_session, load_session, save_session
from amosclaud_agent_sdk.transcript_mirror_batcher import transcript_batches


def test_session_round_trip_summary_and_mutations(tmp_path):
    store = SessionStore(tmp_path)
    session = create_session(store, session_id="session-1", metadata={"project": "website"})
    session.append("user", "Build an investment platform")
    session.append("assistant", "What users will it serve?")
    save_session(store, session)
    restored = load_session(store, "session-1")
    assert summarize_session(restored)["messages"] == 2
    assert update_metadata(store, "session-1", {"stage": "intake"}).metadata["stage"] == "intake"
    assert len(truncate_messages(store, "session-1", 1).messages) == 1


def test_session_validation_paths_and_transcript_batches(tmp_path):
    store = SessionStore(tmp_path)
    session = create_session(store, session_id="safe-session")
    for number in range(3):
        session.append("user", f"message-{number}")
    assert [len(batch) for batch in transcript_batches(session.messages, max_messages=2)] == [2, 1]
    assert validate_session_document(session.to_dict()) == []
    try:
        store.path("../escape")
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe session id accepted")
