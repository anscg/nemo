module Channels
  class Posts
    SHOWN = 3

    Post = Struct.new(:channel_id, :ts, :posted_at, :replies, :reactions, :said,
      keyword_init: true) do
      def error = said&.error
      def message = said&.said
    end

    def self.may_read?(viewer, subject_id)
      viewer.present? && subject_id.present? && viewer.user_id == subject_id
    end

    def self.rows(channel_id:, subject_id:, shown: SHOWN)
      Analytics::FctMessage
        .where(channel_id: channel_id, author_id: subject_id, is_reply: false, subtype: nil)
        .order(posted_at: :desc)
        .limit(shown)
        .to_a
    end

    def self.for(channel_id:, subject_id:, shown: SHOWN)
      told = rows(channel_id: channel_id, subject_id: subject_id, shown: shown)
      told.filter_map { |row| post_for(row) }
    end

    def self.post_for(row)
      said = Slack::Message.at(row.channel_id, row.ts)
      return nil if said.error == :not_found

      Post.new(
        channel_id: row.channel_id, ts: row.ts, posted_at: row.posted_at,
        replies: row.reply_count.to_i, reactions: row.reaction_count.to_i, said: said
      )
    end
  end
end
