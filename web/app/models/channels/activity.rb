module Channels
  # the channels where an author may ask nemo how their own post did. a row is
  # the whole setting: present means shown, absent means not
  class Activity
    class Setting < ApplicationRecord
      self.table_name = "app.channel_message_activity"
      self.primary_key = "channel_id"
    end

    def self.shown?(channel_id) = Setting.where(channel_id: channel_id).exists?

    def self.shown_ids = Setting.pluck(:channel_id)
  end
end
