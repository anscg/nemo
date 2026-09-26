require "test_helper"

class FdActionStandingTest < ActionDispatch::IntegrationTest
  setup do
    @me = hold_role!("UME", "community_manager")
    sign_in_as(@me)
    @kase = make_case(opened_at: 3.days.ago)
  end

  def guard!(**over)
    Fd::MemberGuard.create!({
      kind: "shush", subject_id: "USUB", opened_by: "UMOD",
      reason: "being awful", expires_at: 7.days.from_now
    }.merge(over))
  end

  def look(**params)
    get fd_case_standing_path(@kase), params: {
      type_key: "shush", target_user_id: "USUB"
    }.merge(params)
  end

  test "a record only kind never warns, whatever is standing" do
    guard!
    look(type_key: "warning")
    assert_response :success
    assert_no_match(/is already/, response.body)
  end

  test "nothing standing warns about nothing" do
    look
    assert_response :success
    assert_no_match(/is already/, response.body)
  end

  test "a guard on nobody's case says it sits on no case" do
    guard!
    look
    assert_match(/is already/, response.body)
    assert_match(/on no case/, response.body)
    assert_match(/nemo has not carried it yet/, response.body)
  end

  test "a guard on another case links to that case" do
    other = make_case
    guard!(case_id: other.id)
    look
    assert_match(/under case #{other.id}/, response.body)
    assert_match fd_case_path(other.id), response.body
  end

  test "a guard on this case says so and does not link away" do
    guard!(case_id: @kase.id)
    look
    assert_match(/on this case/, response.body)
    assert_no_match(/under case/, response.body)
  end

  test "a workspace guard is not found by a channel scoped kind" do
    guard!
    look(type_key: "channel_ban", channel_id: "C0266FRGV")
    assert_no_match(/is already/, response.body)
  end

  test "a channel ban is only found in the channel it was made in" do
    guard!(kind: "channel_ban", channel_id: "C0266FRGV")
    look(type_key: "channel_ban", channel_id: "C0266FRGV")
    assert_match(/is already/, response.body)

    look(type_key: "channel_ban", channel_id: "CSOMEWHERE")
    assert_no_match(/is already/, response.body)
  end

  test "a lifted guard is not standing any more" do
    guard!(state: "lifted", lifted_at: Time.current, lifted_by: "UMOD")
    look
    assert_no_match(/is already/, response.body)
  end

  test "a guard still being lifted is still standing" do
    guard!(state: "lifting", lifted_by: "UMOD")
    look
    assert_match(/is already/, response.body)
  end

  test "a guard nemo has dropped is called out as not holding" do
    guard!(carry: "failed")
    look
    assert_match(/nemo is not holding it/, response.body)
    assert_match(/flag-crit/, response.body)
  end

  test "a guard done by hand is not blamed on nemo" do
    guard!(carried_by: "by_hand", carry: "held")
    look
    assert_match(/done by hand/, response.body)
    assert_no_match(/nemo/, response.body)
  end

  test "a guard with no end date says that instead of a date" do
    guard!(expires_at: nil)
    look
    assert_match(/with no end date/, response.body)
  end

  test "a signed out visitor is told nothing about who is standing" do
    guard!
    delete logout_path
    look
    assert_redirected_to login_path
    assert_no_match(/is already/, response.body)
  end
end
