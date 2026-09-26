module Fd
  class StandingsController < BaseController
    permit "case.read"

    def show
      @case = Case.find(params[:case_id])
      @guard = MemberGuard.for_action(
        params[:type_key].to_s,
        params[:target_user_id].to_s.upcase.presence,
        channel_id: params[:channel_id].to_s.strip.presence
      )
      @names = Names.for([@guard&.subject_id, @guard&.opened_by].compact)

      render partial: "fd/cases/standing", layout: false,
        locals: { guard: @guard, kase: @case, names: @names }
    end
  end
end
