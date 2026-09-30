# one post, how it did. reached from nemo's "how did this do?" modal, never
# from a list: the author sees their own, nobody else sees anything
class MessagesController < ApplicationController
  before_action { needs(:analytics) }
  before_action :require_reading

  def show
    @channel_id = params[:channel_id]
    @ts = params[:ts]
    @channel = Analytics::DimChannel.find_by(channel_id: @channel_id)
    @shown = Channels::Activity.shown?(@channel_id)
    @post = Analytics::FctMessage.post(@channel_id, @ts) if @shown
    return unless @post

    unless may_community?("analytics.message.read", @post)
      return refuse_community("analytics.message.read")
    end

    @names = Fd::Names.for([@post.author_id])
    @crowd = Analytics::FctChannelSpan.where(channel_id: @channel_id).pick(:total_members)
    @span = Messages::Activity::SPANS.key?(params[:span]) ? params[:span] :
      Messages::Activity.span_for(@post.posted_at)
    @activity = @post.is_reply ? nil : Messages::Activity.for(@channel_id, @ts, posted_at: @post.posted_at)
  end
end
