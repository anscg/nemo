module Fd
  class StandingsController < BaseController
    permit "case.read"

    def show
      kase = Case.find(params[:case_id])
      type_key = params[:type_key].to_s
      standing = MemberGuard.settle(
        type_key,
        params[:target_user_id].to_s.upcase.presence,
        case_id: kase.id,
        channel_id: params[:channel_id].to_s.strip.presence
      )
      names = Names.for([standing.guard&.subject_id, standing.guard&.opened_by].compact)

      render partial: "fd/cases/standing", layout: false,
        locals: { standing: standing, kase: kase, names: names, type_key: type_key }
    end
  end
end
