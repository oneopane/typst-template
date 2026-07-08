# Common project commands for the Typst notes template.

notes := "./tools/notes.py"
init_template := "./tools/init-template.py"

# Open the interactive notes CLI.
default:
    @{{notes}}

# Show CLI help.
help:
    @{{notes}} --help

# Initialize a new notes project from this template.
# Interactive: just init
# Direct:      just init ../my-notes "My Notes"
init target="" title="" *args:
    @{{init_template}} "{{target}}" "{{title}}" {{args}}

# Open the interactive notes CLI.
ui:
    @{{notes}} interactive

# Show the src/ content tree.
tree:
    @{{notes}} structure

# Show the include graph rooted at main.typ.
map:
    @{{notes}} map

# Write the include graph to a Markdown file.
map-write path="CONTENTS.md":
    @{{notes}} map --write {{path}}

# Compile the notes PDF.
build:
    @{{notes}} build

# Rebuild automatically when files change.
watch:
    @{{notes}} watch

# Serve the PDF at localhost with browser auto-refresh.
serve port="8000":
    @{{notes}} serve --port {{port}}

# Create a new content file or section and update the parent include.
# File:    just new src 02_topic
# Section: just new src 03_probability/
new dir slug title="":
    @{{notes}} new "{{dir}}" "{{slug}}" "{{title}}"

# Preview creating a new content file or section without changing files.
new-dry dir slug title="":
    @{{notes}} new "{{dir}}" "{{slug}}" "{{title}}" --dry-run

# Promote a content file to a section directory.
promote path:
    @{{notes}} promote "{{path}}"

# Preview promotion without changing files.
promote-dry path:
    @{{notes}} promote "{{path}}" --dry-run

# Preview renumbering for immediate children in a directory.
renumber-dry dir="src":
    @{{notes}} renumber "{{dir}}" --dry-run

# Renumber immediate children in a directory and update the parent include.
renumber dir="src":
    @{{notes}} renumber "{{dir}}"

# Validate include graph and repository conventions.
doctor:
    @{{notes}} doctor

# Show or update stable document metadata defaults in notes.toml.
metadata *args:
    @{{notes}} metadata {{args}}

# Summarize labels, bibliography, and image asset references.
labels:
    @{{notes}} labels

bib:
    @{{notes}} bib

assets:
    @{{notes}} assets

# Remove generated outputs.
clean:
    @{{notes}} clean

# Check that the document compiles to a temporary output.
check:
    @{{notes}} check
