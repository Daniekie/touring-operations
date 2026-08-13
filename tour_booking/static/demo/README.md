# Demo images

Referenced by `tour_booking/demo/tour_demo.xml` as

    <field name="image_1920" type="base64" file="tour_booking/static/demo/<name>.jpg"/>

A missing file here is an install-time error, not a blank card, so nothing in
the demo data may point at a name that is not committed alongside it.

Images are resized to 1920px on the long edge and saved at JPEG quality 82
before being committed. Odoo stores `image_1920` in the database and generates
its own thumbnails, so a 6 MB original buys nothing and costs it on every
build.

Drop originals in the repository's `incoming/` directory, which is ignored by
git, and process them from there.
