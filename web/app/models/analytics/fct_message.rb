module Analytics
  class FctMessage < ApplicationRecord
    self.table_name = "analytics.fct_message"
    self.primary_key = nil

    def readonly?
      true
    end

    # the author scope reads this
    def author = author_id

    def self.post(channel_id, ts)
      where(channel_id: channel_id, ts: ts).first
    end
  end
end
