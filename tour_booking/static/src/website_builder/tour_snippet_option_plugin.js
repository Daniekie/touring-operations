import { BuilderAction } from "@html_builder/core/builder_action";
import { SNIPPET_SPECIFIC_END, before } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { registry } from "@web/core/registry";

import { TourBookOption, TourExperiencesOption } from "./tour_snippet_option";

/**
 * Redraw a booking block after one of its options changed.
 *
 * The blocks are shells whose content is fetched by an interaction, so setting
 * `data-tour-id` does nothing visible on its own — the operator would pick an
 * experience and watch nothing happen. Restarting the interaction is what makes
 * the panel and the page agree.
 */
export class ReloadTourSnippetAction extends BuilderAction {
    static id = "reloadTourSnippet";
    static dependencies = ["edit_interaction"];

    apply({ editingElement }) {
        this.dependencies.edit_interaction.restartInteractions(editingElement);
    }
}

class TourSnippetOptionPlugin extends Plugin {
    static id = "tourSnippetOption";
    resources = {
        builder_options: [
            withSequence(before(SNIPPET_SPECIFIC_END), TourExperiencesOption),
            withSequence(before(SNIPPET_SPECIFIC_END), TourBookOption),
        ],
        builder_actions: { ReloadTourSnippetAction },
        // Lets these blocks be dropped inside a column rather than only as a
        // full-width band, which is the point of the booking box.
        so_content_addition_selector: [".s_tour_dynamic"],
    };
}

registry.category("website-plugins").add(TourSnippetOptionPlugin.id, TourSnippetOptionPlugin);
