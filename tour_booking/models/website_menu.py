"""The Tours menu, kept in step with the experiences.

An operator who publishes a tour expects it to be reachable from the website,
and until now the page existed but nothing linked to it: they had to add every
menu entry by hand, and rename it by hand when they renamed the tour. This does
it for them.

The whole thing is one reconciliation rather than a set of incremental edits.
Working out the difference between "a tour was renamed", "a tour was
unpublished" and "the setting was switched off" and applying each as its own
patch is three ways to leave the menu disagreeing with the catalogue; rebuilding
from the published tours cannot.

Only published tours appear. An unpublished tour's page answers 404, and a menu
entry that 404s is worse than no menu entry — it is a broken link on the front
page of somebody's business.

The shape is a heading with the catalogue as its first entry:

    Tours
      All Experiences   -> /tours
      Sunset Sail       -> /tour/sunset-sail-7
      Blue Hole Dive    -> /tour/blue-hole-dive-8

The catalogue is a child rather than the heading's own link because Odoo makes
that decision for us: `website.menu._compute_url` forces any entry that has
children to "#", since a heading with a dropdown under it opens the dropdown
rather than navigating. Without a child for it, /tours would be unreachable
from the menu the moment the first tour was published.
"""

from odoo import _, api, fields, models


class WebsiteMenu(models.Model):
    _inherit = "website.menu"

    # What makes an entry ours, and therefore ours to remove. Without this,
    # rebuilding the menu would mean guessing from the URL which entries were
    # generated and which the operator wrote — and guessing wrong deletes
    # somebody's hand-made menu.
    tour_menu = fields.Selection(
        [
            ("root", "Tours heading"),
            ("catalog", "All experiences"),
            ("tour", "One experience"),
        ],
        string="Generated Entry",
        help="Set on the entries the Tours menu setting maintains. Entries "
             "without it were made by hand and are never touched.",
    )
    tour_id = fields.Many2one(
        "tour.tour",
        string="Experience",
        ondelete="cascade",
        index="btree_not_null",
        help="Set when this entry was generated for an experience. Deleting "
             "the experience takes the entry with it.",
    )

    @api.model
    def _tour_sync(self):
        """Rebuild the generated menu entries on every website.

        Also called straight from a `<function>` in the module's data, so that
        installing or upgrading builds the menu for tours that were published
        before any of this existed.
        """
        for website in self.env["website"].sudo().search([]):
            self.sudo()._tour_sync_website(website)

    @api.model
    def _tour_sync_website(self, website):
        company = website.company_id or self.env.company
        ours = self.search([
            ("website_id", "=", website.id), ("tour_menu", "!=", False),
        ])

        if not company.tour_auto_menu:
            # Switched off takes the heading with it. It was put there by this
            # code, and an empty "Tours" heading left behind reads as a bug.
            ours.unlink()
            return

        root = ours.filtered(lambda menu: menu.tour_menu == "root")[:1]
        if not root:
            root = self.create({
                "name": _("Tours"),
                "parent_id": website.menu_id.id,
                "website_id": website.id,
                "tour_menu": "root",
            })

        catalog = ours.filtered(lambda menu: menu.tour_menu == "catalog")[:1]
        if not catalog:
            self.create({
                "name": _("All Experiences"),
                "url": "/tours",
                "parent_id": root.id,
                # Above every tour, so the way to see all of them is the first
                # thing in the dropdown rather than the last.
                "sequence": 0,
                "website_id": website.id,
                "tour_menu": "catalog",
            })

        tours = self.env["tour.tour"].sudo().search([
            ("company_id", "=", company.id),
            ("is_published", "=", True),
        ])
        existing = {
            menu.tour_id: menu
            for menu in ours.filtered(lambda menu: menu.tour_menu == "tour")
        }

        for position, tour in enumerate(tours):
            values = {
                "name": tour.name,
                # Written directly rather than through `page_id`: a tour page is
                # a controller route, not a `website.page` record, so there is
                # nothing for the menu to point at but the URL.
                "url": tour.website_url,
                "sequence": position + 1,
            }
            menu = existing.pop(tour, None)
            if not menu:
                self.create(dict(
                    values,
                    parent_id=root.id,
                    website_id=website.id,
                    tour_menu="tour",
                    tour_id=tour.id,
                ))
            elif any(menu[field] != value for field, value in values.items()):
                # Compared before writing so that a sync which changes nothing
                # — the common case, since every tour write triggers one — does
                # not touch a row and does not bump `write_date`.
                menu.write(values)

        # Whatever is left was published when it was made and is not now.
        for menu in existing.values():
            menu.unlink()
