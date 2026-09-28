module Fd
  class AutomodMatch < ApplicationRecord
    self.table_name = "fd.automod_matches"

    belongs_to :watch, class_name: "Fd::AutomodWord", foreign_key: :word_id,
      optional: true, inverse_of: :matches
    belongs_to :kase, class_name: "Fd::Case", foreign_key: :case_id, optional: true,
      inverse_of: false

    scope :newest_first, -> { order(at: :desc, id: :desc) }
    scope :loose, -> { where(case_id: nil) }
    scope :on_case, -> { where.not(case_id: nil) }
    scope :for_member, ->(user_id) { where(user_id: user_id) }

    def on_case? = case_id.present?

    def people_named
      [user_id].compact
    end
  end
end
