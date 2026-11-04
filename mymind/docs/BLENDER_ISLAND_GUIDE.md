# Free professional islands for My World (Blender)

Everything here is free: Blender, the script, and the upload feature in your admin page. No AI credits are used.
You can make **many island looks** (tropical, snowy, desert, candy...). Each person using My World chooses the one they like.

## 1. Get Blender (free)
Download Blender 3.6 or newer from https://www.blender.org/download/ (Windows, Mac, Linux).

## 2. Generate the island bases (one run = a whole set)
1. Open Blender. Click the **Scripting** tab at the top.
2. Click **Open** and choose `mymind/tools/blender_island.py`.
3. Click **Run Script** (the play button).
4. The script makes 8 islands and saves them in an `islands` folder next to your .blend file (or in your home folder if the scene is not saved):
   `island_meadow.glb`, `island_tropical.glb`, `island_snowy.glb`, `island_desert.glb`, `island_autumn.glb`, `island_candy.glb`, `island_volcano.glb`, `island_ocean.glb`.

To make your own theme, copy one line in the `THEMES` list at the top of the script, give it a new name and change the colours, shoreline `wiggle`, rock `depth` and `seed`, then run it again.
From a terminal you can make just one: `blender --background --python tools/blender_island.py -- /output/folder snowy`

### Rules for the island base (important)
- The **flat grass top must be the highest point**. My World treats the highest point as the ground the children walk on.
  Do not put trees, houses or rocks on top of this model. Make those as separate landmark models.
- Keep it light: under about 10,000 triangles and under 10 MB. The script's default is about 1,000 triangles.
- Size does not matter. My World rescales the model to fit.

## 3. Make it more professional (optional)
- **Sculpt or refine**: select `IslandBase`, press Tab, and move vertices on the underside to make it more dramatic.
- **Colours**: in the Material tab change the Base Color of Grass, Sand and Rock.
- **Landmarks** (a cottage, a TV, a drum...): model them in Blender, or start from free **CC0** packs
  (Kenney.nl, Quaternius.com, Poly Haven). Only use assets whose licence allows commercial use, and keep the licence note.
- Do not use real people, brands, teams or copyrighted characters.

## 4. Export from Blender yourself (if you changed the model)
File > Export > **glTF 2.0 (.glb/.gltf)** with these settings:
- Format: **glTF Binary (.glb)**
- Include: tick **Selected Objects** if you only want the selected island
- Transform: **+Y Up** (default)
- Mesh: **Apply Modifiers** ticked
- Materials: Export; Images: **JPEG** or WebP for photo textures (keeps files small)
- Compression: leave off (the server optimises it if `gltf-transform` is installed)

## 5. Upload them to your app (repeat for each island)
1. Sign in as the administrator and open **Admin > AI 3D** (`/admin/3d`).
2. In **Upload your own model (free, from Blender)** choose **Island piece: Island base**.
3. Pick one `.glb` file and type the **name people will see**, for example `Tropical Beach`.
4. Leave **Show it in My World right away** ticked and press **Upload**:
   - **Show it in My World right away**: the island is live immediately for every user. No Publish button needed.
   - **Make this the default island** (leave unticked unless you want to change it): users who have not chosen an island see the default. The very first island you upload becomes the default automatically.
5. Repeat for each island. Tick "make default" only on the island you want everyone to start with.

## 6. How people choose their island
- Everyone starts on the **default island**.
- In **My World**, tap the settings (gear) button. Once at least one island is published, an **Island look** menu appears:
  *Automatic (default island)*, *Classic (built-in)*, and each of your islands by name. Press **Save**.
- Each account keeps its own choice. *Automatic* always follows whichever island you marked as default.
- To take an island away, open its model page and press **Unpublish**. Anyone who had chosen it goes back to the default island. If you unpublish the default, the newest published island becomes the default.
- Landmarks (Home, Pictures, Videos...) are shared by all islands.

For a landmark, choose the place (Home, Pictures, Videos, Shorts, Music...) in step 2 instead. It stands on that place's island.

## If the upload is refused
| Message | Fix |
|---|---|
| "not a GLB model" | Export as **glTF Binary (.glb)**, not .gltf or .fbx |
| "points to outside files" | Use .glb so textures are packed inside |
| "no mesh in it" | Select your objects before exporting, or untick "Selected Objects" |
| "too heavy for phones" | Add a **Decimate** modifier, or reduce subdivision, then export again |
| file over 25 MB | Shrink textures (1024 px is plenty) |