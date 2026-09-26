import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static values = { url: String }

  look() {
    const frame = this.element.querySelector("turbo-frame#action-standing")
    if (!frame) return

    const form = this.element.querySelector("form")
    if (!form) return

    const said = new FormData(form)
    const asked = new URLSearchParams({
      type_key: said.get("type_key") ?? "",
      target_user_id: said.get("target_user_id") ?? "",
      channel_id: said.get("channel_id") ?? ""
    })
    frame.src = `${this.urlValue}?${asked}`
    frame.reload()
  }
}
