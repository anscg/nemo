require "test_helper"

class FdThreadGuardsTest < ActionDispatch::IntegrationTest
  setup do
    @me = hold_role!("UME", "community_manager")
    sign_in_as(@me)
    @kase = make_case(subject: "USUB")
  end

  def guard!(**over)
    Fd::ThreadGuard.create!({
      kind: "lock", channel_id: "C0266FRGV", thread_ts: "1700000000.000100",
      opened_by: "UMOD", reason: "it was going nowhere", state: "running",
      expires_at: 3.days.from_now, case_id: @kase.id
    }.merge(over))
  end

  def actions_tab
    get fd_case_path(@kase, tab: "actions")
    response.body
  end

  test "a locked thread on the case is shown beside its actions" do
    guard!
    said = actions_tab

    assert_match(/Thread locked/, said)
    assert_match(/it was going nowhere/, said)
    assert_match(/running/, said)
  end

  test "a destroyed thread reads as destroyed" do
    guard!(kind: "destroy", expires_at: nil, state: "done")
    assert_match(/Thread destroyed/, actions_tab)
  end

  test "a guard that failed is called out" do
    guard!(state: "failed", error: "the admin account could not be invited")
    said = actions_tab
    assert_match(/failed/, said)
    assert_match(/state-crit/, said)
  end

  test "a thread guard on another case is not shown here" do
    other = make_case
    guard!(case_id: other.id)
    assert_no_match(/Thread locked/, actions_tab)
  end

  test "a thread guard tied to no case is shown nowhere" do
    guard!(case_id: nil)
    assert_no_match(/Thread locked/, actions_tab)
  end
end
