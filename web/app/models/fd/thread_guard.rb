module Fd
  class ThreadGuard < ApplicationRecord
    self.table_name = "fd.thread_guards"

    LOCK = "lock".freeze
    DESTROY = "destroy".freeze

    STILL_ON = %w[warned running].freeze

    belongs_to :kase, class_name: "Fd::Case", foreign_key: :case_id, optional: true,
      inverse_of: false

    scope :still_on, -> { where(state: STILL_ON) }
    scope :for_case, ->(case_id) { where(case_id: case_id) }
    scope :newest_first, -> { order(created_at: :desc) }

    def locking? = kind == LOCK
    def destroying? = kind == DESTROY
    def still_on? = STILL_ON.include?(state)
    def failed? = state == "failed"

    def people_named
      [opened_by].compact
    end
  end
end
