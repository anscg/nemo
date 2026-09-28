module Fd
  class ConfigurationController < BaseController
    permit "app.configure"

    TABS = %w[automod].freeze
    SHOWN = 50

    def show
      @tab = params[:tab].presence_in(TABS) || TABS.first
      @words = AutomodWord.watching
      @retired = AutomodWord.retired.newest_first.limit(SHOWN).to_a
      @matches = AutomodMatch.newest_first.limit(SHOWN).to_a
      @channels = ChannelNames.for(@matches.map(&:channel_id))
      @names = Names.for([@words.flat_map(&:people_named),
                          @retired.flat_map(&:people_named),
                          @matches.map(&:user_id)])
    end
  end
end
