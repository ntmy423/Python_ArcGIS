library(sf)
library(mapview)
library(tigris)
library(dplyr)

setwd("\\\\econha01/Client/Arcgis Application/Make A Shapefile/") # <-- Update to your directory path

############################################
#### Check Shapefile Download ##############
############################################

check <- st_read("Input/Test/Philly/selection.shp") # <-- Update to Your file path

mapview(check)
any(st_geometry_type(check) == "MULTIPOLYGON") # If true run the next section to fix the munitpolygon
                                              # then save

if (any(st_geometry_type(check) == "MULTIPOLYGON")) {
  check<- st_cast(check, "POLYGON")
}

#### Save Check
st_write(check, "Output/Test/Philly_New.shp", delete_dsn = TRUE) # <-- Update File Path
####

############################################
#### For Single Point Buffers ##############
############################################

# Input Coordinates from Google Maps (right click, copy coordinates, and transpose so they are written as y, x )
coords <- data.frame(
  lon = -112.08691498560191, # <-- Change This
  lat = 33.59400686004827 # <-- Change This
)

# Input Buffer Distance (Must use feet)

buffer <- 1000 # <-- Change This

#### Preparing Points ####

point_sf <- st_as_sf(coords, coords = c("lon", "lat"), crs = 4326)
point_sf <- point_sf %>% st_transform(2272)
buffer_sf<- st_buffer(point_sf, dist = buffer)

mapview(point_sf) + mapview(buffer_sf)

#### Save Single Point Buffer
st_write(buffer_sf, "Output/Test/Shaw_Butte.shp", delete_dsn = TRUE)  # <-- Update File Path
####

############################################
#### For Multi-Point Buffers ##############
############################################

# To draw own points 
#  1. Go to https://geojson.io/
#  2. Select updise down tear drop on the right side of map
#  3. Click on map to add points
#  4. Click on points to add "Label" in the left box, and the name of the point in the right box, then press save
#  5. Go to the upper left menu, press save, and save as "Shapefile"
#  6. Update file path above to new shapefile

downloaded_sf <- st_read("Input/Test/Points/POINT.shp") # <-- Change This

# Input Buffer Distance (Must use feet) ####

buffer_1 <- 3000 # <-- Change This

downloaded_sf <- downloaded_sf %>% st_transform(2272)
downloaded_buffer_sf<- st_buffer(downloaded_sf, dist = buffer_1)

mapview(downloaded_buffer_sf)

#### Save Multipoint
st_write(downloaded_buffer_sf, "Output/Test/NYC_Points.shp", delete_dsn = TRUE) # <--- Update File Path
####

############################################
#### For Census Geographies ################
############################################

##########################
#### To Pull a State ####

state <- "AZ" # <-- Change This

state <- tigris::states(cb = TRUE, resolution = "500k") %>%
  filter(STUSPS == state) %>%
  sf::st_simplify()

if (any(st_geometry_type(state) == "MULTIPOLYGON")) {
  state <- st_cast(state, "POLYGON")
}

mapview(state)

#### Save State
st_write(state, "Output/Test/Arizona.shp", delete_dsn = TRUE)  # <-- Update File Path
####

##########################
#### To Pull a County ####

state_2 <- "PA" # <-- Change This
name <- "Bucks" # <-- Change This

county <- tigris::counties(cb = TRUE, resolution = "500k") %>%
  filter(STUSPS == state_2, NAME == name) %>%  # update 
  sf::st_simplify()


if (any(st_geometry_type(county) == "MULTIPOLYGON")) {
  county<- st_cast(county, "POLYGON")
}

mapview(county)

#### Save County
st_write(county, "Output/Test/Bucks.shp", delete_dsn = TRUE)  # <-- Update File Path
####

################################
#### To pull a municipality ####

state_3 <- "MA" # <-- Change This
places_list <- places(state = state_3, cb = TRUE)
muni <- "Boston" # <-- Change This

municipality <- places_list %>% filter(NAME == muni)

if (any(st_geometry_type(municipality) == "MULTIPOLYGON")) {
  municipality<- st_cast(municipality, "POLYGON")
}

mapview(municipality)

#### Save Municipality
st_write(municipality, "Output/Test/Boston.shp", delete_dsn = TRUE)  # <-- Update File Path
####

###############################
#### To pull census tracts ####

state_4 <- "MA" # <-- Change This
tract_list <- tracts(state = state_4, cb = TRUE)
tracts <- c("Census Tract 502", # <-- Change This
            "Census Tract 820") # <-- Change This

tracts_final <- tract_list %>% filter(NAMELSAD == tracts)

if (any(st_geometry_type(municipality) == "MULTIPOLYGON")) {
  municipality<- st_cast(municipality, "POLYGON")
}

mapview(tracts_final)

#### Save Tracts
st_write(tracts_final, "Output/Test/Boston_Tracts.shp", delete_dsn = TRUE)  # <-- Update File Path
####

############################################
#### To Combine Geographies ################
############################################

# <--- select geographies, add more letters if need more geographies
a <- buffer_sf
b <- check
c <- state

crs <- 4326  # defining the projection. this must be the same for all binded shapefiles.
             # 4326 is a standard projction, but can change if needed

# Below is an example. You will need to adjust the the specifics of the columns in your shapefile
  # The goal is to make sure all shapefiles have the same column names
  # A label  column identifying the geography and the "geometry" column are necessary

# Check the columns in your shapefile

colnames(a)
colnames(b)
colnames(c)

a$geography <- "Study Area" # Since "a" has only geometry, I'm adding another column ("geography") to label it

b <- b %>% select(shape_name, geometry) # selecting only the label and geometry coulmn
b <- b %>% rename(geography = shape_name) # changing the name of shape_name so it aligns with the columns in a

c <- c %>% select(NAME, geometry)
c <- c %>% rename(geography = NAME)

# Using the previously defined CRS to ensure the CRS of all spaefiles are the same
a <- a %>% st_transform(crs)
b <- b %>% st_transform(crs)
c <- c %>% st_transform(crs)

# Mapping to visually check these shapefiles look right
mapview(a) + mapview(b) + mapview(c)

# Binding sf
binded_sf <- rbind(a, b, c)

# A final visual check of the bound file
mapview(binded_sf)
head(binded_sf)

#### Save combined geography
st_write(binded_sf, "Output/Test/combo_geo.shp", delete_dsn = TRUE)  # <-- Update File Path
####


