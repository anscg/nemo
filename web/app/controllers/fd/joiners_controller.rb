module Fd
  class JoinersController < BaseController
    permit "case.read"

    def index
      @query = JoinerQuery.new(params, actor: current_account)
      @rows = @query.rows
      @views = @query.views
      @names = Names.for(@rows.map(&:user_id))
      log_identity_reads
    end

    private

    def log_identity_reads
      return unless @query.identity?

      shown = @rows.select { |row| row.email.present? }.map(&:user_id)
      return if shown.empty?

      AccessLog.record_many!(actor: current_account, subject_user_ids: shown,
        field_class: "identity_search")
    end
  end
end
