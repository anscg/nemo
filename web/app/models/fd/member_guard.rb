module Fd
  class MemberGuard < ApplicationRecord
    self.table_name = "fd.member_guards"

    SHUSH = "shush".freeze
    CHANNEL_BAN = "channel_ban".freeze
    KINDS = [SHUSH, CHANNEL_BAN].freeze

    LIVE = "live".freeze
    LIFTING = "lifting".freeze
    LIFTED = "lifted".freeze
    STILL_ON = [LIVE, LIFTING].freeze

    PENDING = "pending".freeze
    HELD = "held".freeze
    FAILED = "failed".freeze

    BY_HAND = "by_hand".freeze

    CARRY = "carry".freeze
    ALREADY_DONE = "by_hand".freeze
    ADOPT = "adopt".freeze
    EXTEND = "extend".freeze
    RECORD = "record".freeze

    UNGUARDED = :unguarded
    ORPHANED = :orphaned
    ELSEWHERE = :elsewhere
    HERE = :here

    has_many :events, class_name: "Fd::MemberGuardEvent", foreign_key: :guard_id,
      inverse_of: :guard, dependent: :destroy
    has_many :actions, class_name: "Fd::Action", foreign_key: :guard_id,
      inverse_of: :guard, dependent: :nullify
    belongs_to :kase, class_name: "Fd::Case", foreign_key: :case_id, optional: true,
      inverse_of: false

    scope :still_on, -> { where(state: STILL_ON) }
    scope :live, -> { where(state: LIVE) }
    scope :orphaned, -> { live.where(case_id: nil) }
    scope :stuck, -> { where(carry: FAILED) }
    scope :oldest_first, -> { order(:opened_at, :id) }
    scope :for_subject, ->(subject_id) { where(subject_id: subject_id) }

    Standing = Struct.new(:enforceable, :guard, :reads, :case_id, keyword_init: true) do
      def found? = guard.present?
      def enforceable? = enforceable
    end

    def self.settle(type_key, subject_id, case_id: nil, channel_id: nil)
      unless Action.enforceable?(type_key)
        return Standing.new(enforceable: false, guard: nil, reads: UNGUARDED, case_id: case_id)
      end

      guard = subject_id.present? ? for_action(type_key, subject_id, channel_id: channel_id) : nil
      Standing.new(enforceable: true, guard: guard, case_id: case_id,
        reads: guard ? guard.reads_for(case_id) : UNGUARDED)
    end

    def self.standing_for(subject_id, kind:, channel_id: nil)
      still_on.find_by(subject_id: subject_id, kind: kind, channel_id: channel_id)
    end

    def self.for_action(type_key, subject_id, channel_id: nil)
      kind = Action.guard_kind(type_key)
      return nil if kind.nil?

      where = Action.guard_scope(type_key) == "channel" ? channel_id : nil
      standing_for(subject_id, kind: kind, channel_id: where)
    end

    def live? = state == LIVE
    def lifting? = state == LIFTING
    def held? = carry == HELD
    def failed? = carry == FAILED
    def by_hand? = carried_by == BY_HAND
    def orphaned? = case_id.nil?
    def channel_scoped? = channel_id.present?

    def reads_for(on_case_id)
      return ORPHANED if orphaned?
      return HERE if on_case_id.present? && case_id == on_case_id

      ELSEWHERE
    end

    def people_named
      [opened_by, lifted_by].compact
    end
  end
end
