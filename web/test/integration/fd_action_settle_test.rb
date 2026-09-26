require "test_helper"

class FdActionSettleTest < ActionDispatch::IntegrationTest
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

  def act(**params)
    post fd_case_actions_path(@kase), params: {
      type_key: "shush", target_user_id: "USUB", reason: "would not let it go",
      expires_on: 7.days.from_now.to_date.to_s
    }.merge(params)
  end

  def guards
    Fd::MemberGuard.for_subject("USUB")
  end

  def logged
    @kase.actions.order(:id).last
  end

  def told(verb)
    Fd::AuditEntry.where(entity_type: "member_guard", verb: verb)
  end

  test "carrying it out opens a guard nemo has not done yet, linked to the action" do
    act(settle: Fd::MemberGuard::CARRY)
    guard = guards.sole
    assert_equal "shush", guard.kind
    assert_equal @kase.id, guard.case_id
    assert_equal "nemo", guard.carried_by
    assert_equal "pending", guard.carry
    assert_equal guard.id, logged.guard_id
    assert_equal 1, told("opened").count
  end

  test "one already done by hand is opened as held" do
    act(settle: Fd::MemberGuard::ALREADY_DONE)
    guard = guards.sole
    assert guard.by_hand?
    assert guard.held?
  end

  test "a record only kind writes no guard at all" do
    act(type_key: "warning", expires_on: nil)
    assert_empty guards
    assert_nil logged.guard_id
    assert_empty told("opened")
  end

  test "a workspace kind is opened without the channel it was handed" do
    act(settle: Fd::MemberGuard::CARRY, channel_id: "C0266FRGV")
    assert_nil guards.sole.channel_id
  end

  test "a channel ban keeps the channel it was made in" do
    act(type_key: "channel_ban", settle: Fd::MemberGuard::CARRY, channel_id: "C0266FRGV")
    assert_equal "C0266FRGV", guards.sole.channel_id
  end

  test "adopting an orphan puts it on this case and links the action" do
    orphan = guard!
    act(settle: Fd::MemberGuard::ADOPT)
    assert_equal @kase.id, orphan.reload.case_id
    assert_equal orphan.id, logged.guard_id
    assert_equal 1, told("attached").count
    assert_equal 1, guards.count
  end

  test "an orphan left alone is neither moved nor linked" do
    orphan = guard!
    act(settle: Fd::MemberGuard::RECORD)
    assert_nil orphan.reload.case_id
    assert_nil logged.guard_id
    assert_empty told("attached")
  end

  test "extending moves the date on the guard that already exists" do
    other = make_case
    held = guard!(case_id: other.id)
    fresh = 30.days.from_now.to_date
    act(settle: Fd::MemberGuard::EXTEND, expires_on: fresh.to_s)
    assert_equal fresh, held.reload.expires_at.to_date
    assert_equal held.id, logged.guard_id
    assert_equal 1, told("extended").count
  end

  test "a guard under another case left alone is not claimed" do
    other = make_case
    held = guard!(case_id: other.id)
    act(settle: Fd::MemberGuard::RECORD)
    assert_equal other.id, held.reload.case_id
    assert_nil logged.guard_id
  end

  test "a guard already on this case is linked without being changed" do
    held = guard!(case_id: @kase.id)
    was = held.expires_at
    act(settle: Fd::MemberGuard::RECORD)
    assert_equal held.id, logged.guard_id
    assert_equal was.to_i, held.reload.expires_at.to_i
    assert_empty told("attached")
    assert_empty told("extended")
  end

  test "a second shush cannot open a second guard on the same person" do
    guard!(case_id: @kase.id)
    act(settle: Fd::MemberGuard::CARRY)
    assert_equal 1, guards.count
  end

  test "nothing is written at all when the action itself is refused" do
    drop_roles!("UME")
    hold_role!("UME", "gardener")
    act(settle: Fd::MemberGuard::CARRY)
    assert_empty guards
    assert_empty @kase.actions
  end
end
