import app


def test_the_bot_reads_message_activity_on_the_internal_credential():
    assert "insights.messageStats" in app.NEMO_METHODS["internal"]
    assert "insights.messageStats" in app.WEB_METHODS["internal"]


def test_message_activity_is_never_logged_as_a_write():
    assert "insights.messageStats" not in app.WRITES


def test_the_bot_still_writes_only_on_the_admin_credential():
    assert app.NEMO_METHODS["admin"] == app.WRITE_METHODS["admin"]
    assert "insights.messageStats" not in app.NEMO_METHODS["admin"]


def test_the_pipeline_does_not_get_the_new_method_for_free():
    assert "insights.messageStats" not in app.ALLOWED_METHODS["internal"]
