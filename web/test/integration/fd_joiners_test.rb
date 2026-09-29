require "test_helper"

class FdJoinersTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    @me = hold_role!("UME", "community_manager")
  end

  def joined!(user_id, at:, source: "team_join", email: nil)
    member!(user_id, email: email)
    as_pipeline("INSERT INTO fd.member_joins (user_id, joined_at, source) VALUES (?, ?, ?) " \
                "ON CONFLICT (user_id) DO UPDATE SET joined_at = EXCLUDED.joined_at, " \
                "source = EXCLUDED.source", user_id, at, source)
    seeded!("fd.member_joins", "user_id", user_id)
  end

  def query(params = {}, actor: @me)
    Fd::JoinerQuery.new(params.stringify_keys, actor: actor)
  end

  test "the window is what was asked for, not everything ever" do
    joined!("UNEW1", at: 2.hours.ago)
    joined!("UOLD1", at: 40.days.ago)

    assert_includes query({ "when" => "week" }).rows.map(&:user_id), "UNEW1"
    assert_not_includes query({ "when" => "week" }).rows.map(&:user_id), "UOLD1"
    assert_includes query({ "when" => "any" }).rows.map(&:user_id), "UOLD1"
  end

  test "two who arrived within two minutes read as a burst" do
    joined!("UB1", at: 3.hours.ago)
    joined!("UB2", at: 3.hours.ago + 30.seconds)
    joined!("ULONE", at: 2.days.ago)

    caught = query({ "view" => "burst" }).rows.map(&:user_id)
    assert_includes caught, "UB1"
    assert_includes caught, "UB2"
    assert_not_includes caught, "ULONE"
  end

  test "a backfilled join is never counted as a burst, its clock is only a day wide" do
    joined!("UC1", at: 3.hours.ago, source: "cohort")
    joined!("UC2", at: 3.hours.ago, source: "cohort")

    assert_empty query({ "view" => "burst" }).rows
    assert_nil query({ "when" => "week" }).rows.find { |row| row.user_id == "UC1" }.nearest_join
  end

  test "email is only there for somebody who may read identity" do
    joined!("UE1", at: 1.hour.ago, email: "kid@school.example")

    row = query.rows.find { |one| one.user_id == "UE1" }
    assert_equal "kid@school.example", row.email
    assert_equal "school.example", row.domain

    blind = Fd::JoinerQuery.new({}, actor: nil)
    assert_nil blind.rows.find { |one| one.user_id == "UE1" }.email
  end

  test "a domain nobody else uses is called out, a shared one is not" do
    joined!("UD1", at: 1.hour.ago, email: "one@lonely.example")
    joined!("UD2", at: 1.hour.ago, email: "two@shared.example")
    joined!("UD3", at: 2.hours.ago, email: "three@shared.example")

    rows = query.rows.index_by(&:user_id)
    assert rows["UD1"].lone_domain?
    assert_not rows["UD2"].lone_domain?
    assert_equal 2, rows["UD2"].domain_people
  end

  test "somebody under a guard and somebody deactivated are told apart" do
    joined!("UG1", at: 1.hour.ago)
    joined!("UG2", at: 1.hour.ago)
    Fd::MemberGuard.create!(kind: "shush", subject_id: "UG1", opened_by: "UME",
      reason: "spam", carried_by: "nemo", carry: "held", expires_at: 2.days.from_now)
    Fd::MemberGuard.create!(kind: "deactivation", subject_id: "UG2", opened_by: "UME",
      reason: "raiding", carried_by: "nemo", carry: "held")

    rows = query.rows.index_by(&:user_id)
    assert rows["UG1"].guarded?
    assert_not rows["UG1"].deactivated?
    assert rows["UG2"].deactivated?

    assert_equal ["UG1"], query({ "view" => "guarded" }).rows.map(&:user_id) - ["UG2"]
    assert_equal ["UG2"], query({ "view" => "gone" }).rows.map(&:user_id)
  end

  test "the tab counts are over the window, not over the tab you are on" do
    joined!("UT1", at: 1.hour.ago)
    joined!("UT2", at: 1.hour.ago + 20.seconds)
    Fd::MemberGuard.create!(kind: "deactivation", subject_id: "UT1", opened_by: "UME",
      reason: "raiding", carried_by: "nemo", carry: "held")

    counts = query({ "view" => "gone" }).views.index_by(&:key)
    assert_equal 2, counts["newest"].count
    assert_equal 2, counts["burst"].count
    assert_equal 1, counts["gone"].count
  end

  test "a domain filter nobody may read is refused rather than applied" do
    joined!("UF1", at: 1.hour.ago, email: "kid@school.example")

    blind = Fd::JoinerQuery.new({ "domain" => "school.example" }, actor: nil)
    assert_equal "any", blind["domain"]
    assert_includes blind.rows.map(&:user_id), "UF1"
  end

  test "the page opens and lists who joined" do
    joined!("UP1", at: 1.hour.ago, email: "kid@school.example")
    sign_in_as(@me)

    get fd_joiners_path
    assert_response :success
    assert_select "turbo-frame#joiners"
    assert_match "school.example", response.body
  end

  test "reading the emails on the page is written down against the reader" do
    joined!("UL1", at: 1.hour.ago, email: "kid@school.example")
    sign_in_as(@me)

    assert_difference -> { AccessLog.where(field_class: "identity_search").count }, 1 do
      get fd_joiners_path
    end
    assert_equal "UL1", AccessLog.where(field_class: "identity_search").last.subject_user_id
  end

  test "a tab and a date range hold at the same time" do
    asked = query({ "view" => "burst", "when" => "day" })

    assert_equal "burst", asked.view, "picking a window must not drop the tab"
    assert_equal "day", asked["when"]
    assert_equal "burst", asked.window_params("month")["view"]
    assert_equal "day", asked.view_params("gone")["when"]
  end

  test "a search holds across a tab and a window" do
    asked = query({ "view" => "burst", "when" => "day", "q" => "zev" })

    assert_equal "zev", asked.term
    assert_equal "zev", asked.window_params("month")["q"]
    assert_equal "zev", asked.view_params("gone")["q"]
    assert_equal "burst", asked.view
  end

  test "a search finds them by handle, and by email only if identity is readable" do
    joined!("US1", at: 1.hour.ago, email: "findme@school.example")

    assert_includes query({ "q" => "us1" }).rows.map(&:user_id), "US1"
    assert_includes query({ "q" => "findme" }).rows.map(&:user_id), "US1"
    blind = Fd::JoinerQuery.new({ "q" => "findme" }, actor: nil)
    assert_not_includes blind.rows.map(&:user_id), "US1"
  end

  test "picking several and confirming the count deactivates each one" do
    joined!("UX1", at: 1.hour.ago)
    joined!("UX2", at: 1.hour.ago)
    sign_in_as(@me)

    post fd_bulk_deactivations_path, params: {
      user_ids: %w[UX1 UX2], reason: "joined together and posted the same link"
    }

    assert_equal 2, Fd::MemberGuard.where(kind: "deactivation", subject_id: %w[UX1 UX2]).count
    assert_equal %w[pending], Fd::MemberGuard.where(subject_id: %w[UX1 UX2])
      .pluck(:carry).uniq
  end

  test "a bulk deactivation with nobody picked changes nothing" do
    sign_in_as(@me)

    assert_no_difference -> { Fd::MemberGuard.count } do
      post fd_bulk_deactivations_path, params: { user_ids: [], reason: "raiding" }
    end
    assert_match(/pick who this is about/, flash[:alert])
  end

  test "the reason is carried when there is one, and named when there is not" do
    joined!("UZ1", at: 1.hour.ago)
    joined!("UZ2", at: 1.hour.ago)
    sign_in_as(@me)

    post fd_bulk_deactivations_path, params: { user_ids: %w[UZ1], reason: "invite spam" }
    assert_equal "invite spam", Fd::MemberGuard.find_by(subject_id: "UZ1").reason

    post fd_bulk_deactivations_path, params: { user_ids: %w[UZ2], reason: " " }
    assert_equal Fd::BulkDeactivationsController::NO_REASON,
      Fd::MemberGuard.find_by(subject_id: "UZ2").reason
  end

  test "somebody who may not deactivate cannot do it in bulk either" do
    joined!("UW1", at: 1.hour.ago)
    Authz::Override.create!(role: "firefighter", capability: "member.deactivate",
      allowed: false, changed_by: "UME")
    sign_in_as(hold_role!("UFF", "firefighter"))

    post fd_bulk_deactivations_path, params: { user_ids: %w[UW1], reason: "raiding" }

    assert_empty Fd::MemberGuard.where(subject_id: "UW1")
  end

  test "one already standing is counted apart rather than opened twice" do
    joined!("UV1", at: 1.hour.ago)
    Fd::MemberGuard.create!(kind: "deactivation", subject_id: "UV1", opened_by: "UME",
      reason: "already", carried_by: "nemo", carry: "held")
    sign_in_as(@me)

    post fd_bulk_deactivations_path, params: { user_ids: %w[UV1], reason: "again" }

    assert_equal 1, Fd::MemberGuard.where(subject_id: "UV1").count
    assert_match(/already had one standing/, flash[:notice])
  end

  test "the standing column names the guard rather than counting it" do
    joined!("UK1", at: 1.hour.ago)
    Fd::MemberGuard.create!(kind: "shush", subject_id: "UK1", opened_by: "UME",
      reason: "spam", carried_by: "nemo", carry: "held", expires_at: 2.days.from_now)

    assert_equal %w[shush], query.rows.find { |row| row.user_id == "UK1" }.kinds
  end

  test "nothing is written down when there was no identity to read" do
    joined!("UN1", at: 1.hour.ago)
    sign_in_as(@me)

    assert_no_difference -> { AccessLog.count } do
      get fd_joiners_path
    end
  end
end
