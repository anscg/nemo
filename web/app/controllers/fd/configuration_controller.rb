module Fd
  class ConfigurationController < BaseController
    permit "app.configure"

    TABS = %w[automod responses].freeze
    SHOWN = 50

    def show
      @tab = params[:tab].presence_in(TABS) || TABS.first
      @words = AutomodWord.watching
      @retired = AutomodWord.retired.newest_first.limit(SHOWN).to_a
      @matches = AutomodMatch.newest_first.limit(SHOWN).to_a
      load_responses
      @channels = ChannelNames.for(@matches.map(&:channel_id) + [@autoresponse_channel])
      @names = Names.for([@words.flat_map(&:people_named),
                          @retired.flat_map(&:people_named),
                          @matches.map(&:user_id)])
    end

    private

    def load_responses
      @autoresponse_on = AppSetting.on?(AppSetting::AUTORESPONSE_ON)
      @autoresponse_emoji = AppSetting.autoresponse_emoji
      @autoresponse_channel = AppSetting.said(AppSetting::AUTORESPONSE_CHANNEL)
      @autoresponse_body = AppSetting.said(AppSetting::AUTORESPONSE_BODY)
      @autoresponse_cooldown = AppSetting.autoresponse_cooldown_days
      @unsub_on = AppSetting.on?(AppSetting::UNSUB_SHIELD_ON)
      @unsub_link = AppSetting.said(AppSetting::UNSUB_SHIELD_LINK)
    end
  end
end
