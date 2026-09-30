module Messages
  # how one top-level post did, straight from slack's message activity, shaped
  # for the page. the same numbers nemo shows in the modal
  class Activity
    METHOD = "insights.messageStats".freeze
    TTL = 1.minute

    SPANS = {
      "1h" => "First hour",
      "1d" => "First day",
      "1w" => "First week",
      "30d" => "First month"
    }.freeze
    DEFAULT_SPAN = "1d".freeze

    # the unit each span is counted in, and how a tick reads
    UNITS = {
      "1h" => [60, ->(n) { "#{n}m" }],
      "1d" => [3600, ->(n) { "#{n}h" }],
      "1w" => [86_400, ->(n) { "day #{n}" }],
      "30d" => [86_400, ->(n) { "day #{n}" }]
    }.freeze

    CLIENTS = [["browser_count", "browser"], ["desktop_count", "desktop"],
               ["mobile_count", "mobile"]].freeze

    Result = Struct.new(:stats, :error, keyword_init: true)

    def self.for(channel_id, ts, posted_at: nil)
      stats = Rails.cache.fetch("slack/activity/#{channel_id}/#{ts}", expires_in: TTL,
                                                                    skip_nil: true) do
        response = Slack::ProxyClient.call(METHOD, { "channel" => channel_id, "ts" => ts })
        response["stats"] if response["ok"]
      end
      return Result.new(error: :not_found) if stats.nil?

      Result.new(stats: new(stats, posted_at: posted_at))
    rescue Slack::ProxyClient::NotConfigured => e
      Rails.logger.error("message activity proxy is not configured: #{e.message}")
      Result.new(error: :not_configured)
    rescue Slack::ProxyClient::AuthError
      Result.new(error: :reauth)
    rescue Slack::ProxyClient::Error
      Result.new(error: :unavailable)
    end

    def self.span_for(posted_at)
      age = Time.current - posted_at
      return "1h" if age < 2.hours
      return "1d" if age < 2.days
      return "1w" if age < 8.days

      "30d"
    end

    def initialize(stats, posted_at: nil)
      @stats = stats
      @posted_at = posted_at
    end

    # how far into the post's life we are, in seconds
    def age = @posted_at ? (Time.current - @posted_at).to_i : nil

    def viewers = @stats["num_users_viewed"].to_i
    def reacted = @stats["num_users_reacted"].to_i
    def clicked = @stats["num_users_clicked"].to_i
    def shared = @stats["num_shares"].to_i
    def top_reply_ts = @stats["top_threaded_reply_by_reactions_ts"].presence

    # [label, count, share of the whole in percent]
    def clients
      counts = CLIENTS.map { |key, label| [label, (@stats["client_breakdown"] || {})[key].to_i] }
      whole = counts.sum { |_, count| count }
      counts.map { |label, count| [label, count, whole.zero? ? nil : (100.0 * count / whole).round] }
    end

    SPAN_SECONDS = { "1h" => 3600, "1d" => 86_400, "1w" => 7 * 86_400, "30d" => 30 * 86_400 }.freeze

    # new unique viewers per bucket for one span, as [offset seconds, count].
    # slack pads the span out with zeros past the present, so those are dropped
    def curve(span)
      series = ((@stats["viewers_time_series"] || {})["data"] || [])
        .find { |one| one["seriesType"] == span }
      return [] if series.nil?

      points = (series["series"] || []).filter_map do |point|
        next if point["value"].nil?

        [point["value"].to_i / 1_000_000, point["count"].to_i]
      end
      return [] if points.empty?

      start = points.first.first
      points.map { |at, count| [at - start, count] }
        .reject { |offset, _| age && offset > age }
    end

    # the span runs past the present, so the curve is only part of it
    def partial?(span) = age.present? && age < SPAN_SECONDS.fetch(span)

    def seen_within(span) = curve(span).sum(&:last)

    def any_curve? = SPANS.keys.any? { |span| curve(span).size > 1 }

    # what the chart controller draws: one line, ticks said in the span's unit
    def chart(span)
      unit, say = UNITS.fetch(span)
      points = curve(span)
      {
        labels: points.map { |offset, _| say.call((offset / unit.to_f).round(1).then { |n| n == n.to_i ? n.to_i : n }) },
        datasets: [{ label: "new viewers", data: points.map(&:last) }]
      }
    end

    def peak(span)
      curve(span).max_by(&:last)&.last.to_i
    end
  end
end
