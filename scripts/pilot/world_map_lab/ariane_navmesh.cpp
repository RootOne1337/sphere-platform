// Native adapter for Recast/Detour 1.6.0. Public coordinates remain in the
// game's XYZ frame.
#include "DetourCommon.h"
#include "DetourNavMesh.h"
#include "DetourNavMeshBuilder.h"
#include "DetourNavMeshQuery.h"
#include "Recast.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <queue>
#include <unordered_map>
#include <vector>

#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C" __attribute__((visibility("default")))
#endif

struct Chunk {
    const float *xyz;
    uint32_t count, kind;
};
enum Source { Collision, Obstacle, Water, Road, Paving, Foot };
// Paint only physically walkable spans. Zero preserves driving and legacy tiles.
enum WalkArea : unsigned char { LegacyArea, GenericFloor, Carriageway, PavedGround, Footpath };
constexpr unsigned short pavementFlag = 2;
static float travelCost(unsigned char area) {
    switch (area) {
    case Footpath: return 1.f;
    case PavedGround: return 1.18f;
    case GenericFloor: return 1.75f;
    case Carriageway: return 2.5f;
    default: return 1.f;
    }
}
constexpr float ch = 0.125f;
constexpr float tileWidth = 128.f;

static void toNav(const float *xyz, float *v) {
    v[0] = xyz[0];
    v[1] = xyz[2];
    v[2] = -xyz[1];
}
static void toGame(const float *v, float *xyz) {
    xyz[0] = v[0];
    xyz[1] = -v[2];
    xyz[2] = v[1];
}

API int walk_material_version() { return 1; }
API float bake_cell_size(int profile) { return profile == 2 ? 0.125f : 0.25f; }
API int build_tile(const Chunk *chunks, int count, float originX, float originY, int tx, int ty,
                   float ymin, float ymax, int layer, int profile, unsigned char **out,
                   int *bytes) {
    *out = nullptr;
    *bytes = 0;
    rcContext ctx(false);
    const bool drive = profile == 1;
    const bool fine = profile == 2;
    const int tileCells = fine ? 1024 : 512;
    const float cs = bake_cell_size(profile);
    const int radius = drive ? 6 : (fine ? 4 : 2);
    const int climb = drive ? 2 : 3;
    const int height = drive ? 16 : 15;
    const int border = radius + 3;
    const int side = tileCells + 2 * border;
    const float west = originX + tx * tileWidth - border * cs;
    const float north = -originY + ty * tileWidth - border * cs;
    const float bmin[] = {west, ymin, north};
    const float bmax[] = {west + side * cs, ymax, north + side * cs};
    if (ymax - ymin >= RC_SPAN_MAX_HEIGHT * ch)
        return -1;
    rcHeightfield solid, roads, water;
    auto init = [&](rcHeightfield &f) {
        return rcCreateHeightfield(&ctx, f, side, side, bmin, bmax, cs, ch);
    };
    if (!init(solid) || !init(water) || !init(roads))
        return -2;
    const float cosine = drive ? 0.906308f : 0.707107f;
    for (int k = 0; k < count; ++k) {
        const Chunk &batch = chunks[k];
        if (drive && (batch.kind == Paving || batch.kind == Foot))
            continue;
        const bool paint = batch.kind == Road || batch.kind == Paving || batch.kind == Foot;
        rcHeightfield &target = batch.kind == Water ? water : paint ? roads : solid;
        for (uint32_t i = 0; i < batch.count; ++i) {
            float a[3], b[3], c[3];
            const float *xyz = batch.xyz + i * 9;
            toNav(xyz, a);
            toNav(xyz + 3, b);
            toNav(xyz + 6, c);
            float ab[3], ac[3], n[3];
            rcVsub(ab, b, a);
            rcVsub(ac, c, a);
            rcVcross(n, ab, ac);
            float length = std::sqrt(rcVdot(n, n));
            if (length < 1e-6f)
                continue;
            unsigned char area = RC_NULL_AREA;
            if ((batch.kind == Collision && n[1] >= cosine * length) ||
                (batch.kind == Road && std::abs(n[1]) >= cosine * length) || batch.kind == Water)
                area = RC_WALKABLE_AREA;
            if (paint) {
                if (std::abs(n[1]) < cosine * length) continue;
                area = drive ? RC_WALKABLE_AREA :
                       batch.kind == Foot ? Footpath : batch.kind == Paving ? PavedGround : Carriageway;
            }
            if (!rcRasterizeTriangle(&ctx, a, b, c, area, target, 0))
                return -3;
        }
    }
    for (int i = 0; i < side * side; ++i) {
        for (rcSpan *s = solid.spans[i]; s; s = s->next) {
            if (!s->area)
                continue;
            for (rcSpan *w = water.spans[i]; w; w = w->next)
                if (w->smax >= s->smax)
                    s->area = RC_NULL_AREA;
        }
    }
    // This filter compares opposite neighbours, a two-cell baseline. Applying
    // the per-link climb here cuts ordinary road ramps into disconnected bands.
    // Compact-field links and cross-tile portals still use the single-step limit.
    rcFilterLedgeSpans(&ctx, height, 2 * climb, solid);
    rcFilterWalkableLowHeightSpans(&ctx, height, solid);
    rcCompactHeightfield compact;
    if (!rcBuildCompactHeightfield(&ctx, height, climb, solid, compact))
        return -4;
    if (!compact.spanCount)
        return 0;
    // Erode the physically traversable floor with the complete body radius.
    // Paint seams and the roadside material boundary are not vertical obstacles.
    if (!rcErodeWalkableArea(&ctx, radius, compact))
        return -5;
    for (int cell = 0; cell < side * side; ++cell) {
        const auto &column = compact.cells[cell];
        for (unsigned j = column.index; j < column.index + column.count; ++j) {
            if (!compact.areas[j]) continue;
            unsigned char material = drive ? RC_NULL_AREA : GenericFloor;
            for (auto *r = roads.spans[cell]; r; r = r->next) {
                if (std::abs(int(r->smax) - int(compact.spans[j].y)) <= 3)
                    material = std::max(material, static_cast<unsigned char>(r->area));
            }
            compact.areas[j] = material;
        }
    }
    if (!rcBuildRegionsMonotone(&ctx, compact, border, fine ? 48 : 12, fine ? 256 : 64))
        return -5;
    rcContourSet contours;
    if (!rcBuildContours(&ctx, compact, 0.75f, fine ? 64 : 32, contours,
                         RC_CONTOUR_TESS_WALL_EDGES))
        return -6;
    if (!contours.nconts)
        return 0;
    rcPolyMesh mesh;
    if (!rcBuildPolyMesh(&ctx, contours, 6, mesh))
        return -7;
    if (!mesh.npolys)
        return 0;
    for (int i = 0; i < mesh.npolys; ++i) {
        mesh.flags[i] = 1;
        if (drive) mesh.areas[i] = LegacyArea;
    }
    rcPolyMeshDetail detail;
    if (!rcBuildPolyMeshDetail(&ctx, mesh, compact, 3.0f, 0.25f, detail))
        return -8;
    dtNavMeshCreateParams p{};
    p.verts = mesh.verts;
    p.vertCount = mesh.nverts;
    p.polys = mesh.polys;
    p.nvp = mesh.nvp;
    p.polyFlags = mesh.flags;
    p.polyAreas = mesh.areas;
    p.polyCount = mesh.npolys;
    p.detailMeshes = detail.meshes;
    p.detailVerts = detail.verts;
    p.detailVertsCount = detail.nverts;
    p.detailTris = detail.tris;
    p.detailTriCount = detail.ntris;
    p.tileX = tx;
    p.tileY = ty;
    p.tileLayer = layer;
    p.cs = cs;
    p.ch = ch;
    p.buildBvTree = true;
    rcVcopy(p.bmin, mesh.bmin);
    rcVcopy(p.bmax, mesh.bmax);
    p.walkableHeight = height * ch;
    p.walkableClimb = climb * ch;
    p.walkableRadius = radius * cs;
    return dtCreateNavMeshData(&p, out, bytes) ? mesh.npolys : -9;
}
API void free_tile(void *data) { dtFree(data); }

API dtNavMesh *create_nav(float x, float y, int tiles) {
    dtNavMeshParams params{};
    params.orig[0] = x;
    params.orig[2] = -y;
    params.tileWidth = params.tileHeight = tileWidth;
    params.maxTiles = tiles;
    params.maxPolys = 65535;
    auto *nav = dtAllocNavMesh();
    if (nav && dtStatusFailed(nav->init(&params))) {
        dtFreeNavMesh(nav);
        return nullptr;
    }
    return nav;
}
API int add_tile(dtNavMesh *nav, const unsigned char *bytes, int size) {
    auto *copy = (unsigned char *)dtAlloc(size, DT_ALLOC_PERM);
    if (!copy)
        return 0;
    std::memcpy(copy, bytes, size);
    dtTileRef ref = 0;
    if (dtStatusFailed(nav->addTile(copy, size, DT_TILE_FREE_DATA, 0, &ref))) {
        dtFree(copy);
        return 0;
    }
    const dtMeshTile *tile = nav->getTileByRef(ref);
    for (int i = 0; i < tile->header->polyCount; ++i) {
        auto &poly = tile->polys[i];
        if (poly.getArea() == PavedGround || poly.getArea() == Footpath)
            poly.flags |= pavementFlag;
    }
    return 1;
}
API void free_nav(dtNavMesh *nav) { dtFreeNavMesh(nav); }

// Collect exact static connectivity including cross-tile portals. Isolated
// polygons stay isolated.
struct Face {
    float xyz[18];
    uint32_t vertices, group;
};
static int enumerate_components(const dtNavMesh *nav, Face *faces, unsigned *labels, int capacity) {
    std::vector<int> base(nav->getMaxTiles(), -1);
    int n = 0;
    for (int i = 0; i < nav->getMaxTiles(); ++i) {
        auto *t = nav->getTile(i);
        if (t->header) {
            base[i] = n;
            n += t->header->polyCount;
        }
    }
    if ((!faces && !labels) || capacity < n)
        return n;
    std::vector<int> parent(n);
    for (int i = 0; i < n; ++i)
        parent[i] = i;
    auto root = [&](int i) {
        while (parent[i] != i) {
            parent[i] = parent[parent[i]];
            i = parent[i];
        }
        return i;
    };
    for (int i = 0; i < nav->getMaxTiles(); ++i) {
        if (base[i] < 0)
            continue;
        auto *t = nav->getTile(i);
        for (int p = 0; p < t->header->polyCount; ++p) {
            auto &poly = t->polys[p];
            if (faces) {
                auto &f = faces[base[i] + p];
                f.vertices = poly.vertCount;
                for (int v = 0; v < poly.vertCount; ++v)
                    toGame(t->verts + poly.verts[v] * 3, f.xyz + v * 3);
            }
            for (auto l = poly.firstLink; l != DT_NULL_LINK; l = t->links[l].next) {
                auto ref = t->links[l].ref;
                if (!ref)
                    continue;
                int j = nav->decodePolyIdTile(ref);
                int q = nav->decodePolyIdPoly(ref);
                if (base[j] >= 0)
                    parent[root(base[i] + p)] = root(base[j] + q);
            }
        }
    }
    for (int i = 0; i < n; ++i) {
        unsigned label = root(i);
        if (faces)
            faces[i].group = label;
        if (labels)
            labels[i] = label;
    }
    return n;
}

API int collect_faces(const dtNavMesh *nav, Face *faces, int capacity) {
    return enumerate_components(nav, faces, nullptr, capacity);
}
API int collect_labels(const dtNavMesh *nav, unsigned *labels, int capacity) {
    return enumerate_components(nav, nullptr, labels, capacity);
}
static dtStatus endpoint(dtNavMeshQuery &q, const dtQueryFilter &filter, const float *xyz,
                         dtPolyRef &ref, float *hit, float horizontal = 1.5f) {
    const float extents[] = {horizontal, 1.0f, horizontal};
    float point[3];
    toNav(xyz, point);
    auto status = q.findNearestPoly(point, extents, &filter, &ref, hit);
    if (ref && (std::hypot(point[0] - hit[0], point[2] - hit[2]) > horizontal ||
                std::abs(point[1] - hit[1]) > 1.0f))
        ref = 0;
    return status;
}
API int endpoint_index(const dtNavMesh *nav, const float *xyz) {
    dtNavMeshQuery q;
    if (dtStatusFailed(q.init(nav, 64)))
        return -2;
    dtPolyRef ref = 0;
    float hit[3];
    dtQueryFilter filter;
    if (dtStatusFailed(endpoint(q, filter, xyz, ref, hit)))
        return -2;
    if (!ref)
        return -1;
    int index = nav->decodePolyIdPoly(ref);
    for (unsigned i = 0; i < nav->decodePolyIdTile(ref); ++i) {
        const auto *tile = nav->getTile(i);
        if (tile->header)
            index += tile->header->polyCount;
    }
    return index;
}
struct RouteNode {
    float cost;
    dtPolyRef previous;
};
struct OpenPoly {
    float estimate, cost;
    dtPolyRef ref;
    bool operator<(const OpenPoly &other) const {
        if (estimate != other.estimate)
            return estimate > other.estimate;
        return ref > other.ref;
    }
};

static void center(const dtMeshTile *tile, const dtPoly *poly, float *v) {
    v[0] = v[1] = v[2] = 0;
    for (int i = 0; i < poly->vertCount; ++i) {
        const float *p = tile->verts + poly->verts[i] * 3;
        for (int j = 0; j < 3; ++j)
            v[j] += p[j];
    }
    for (int j = 0; j < 3; ++j)
        v[j] /= poly->vertCount;
}

static float distance(const float *a, const float *b) {
    float d[3];
    rcVsub(d, a, b);
    return std::sqrt(rcVdot(d, d));
}

// Each high-level node is a connected set of polygons inside one tile.
// Only real Detour links can connect clusters or form the detailed path.
struct ClusterGraph {
    std::vector<int> offsets, membership;
    std::vector<std::vector<int>> edges;
    struct Position {
        float xyz[3]{};
    };
    std::vector<Position> centers;
    int cluster(const dtNavMesh *nav, dtPolyRef ref) const {
        return membership[offsets[nav->decodePolyIdTile(ref)] + nav->decodePolyIdPoly(ref)];
    }
};
API ClusterGraph *index_clusters(const dtNavMesh *nav) {
    auto *g = new ClusterGraph;
    int total = 0;
    for (int i = 0; i < nav->getMaxTiles(); ++i) {
        const auto *tile = nav->getTile(i);
        g->offsets.push_back(total);
        if (tile->header)
            total += tile->header->polyCount;
    }
    g->membership.assign(total, -1);
    std::vector<int> stack;
    for (int i = 0; i < nav->getMaxTiles(); ++i) {
        auto *tile = nav->getTile(i);
        if (!tile->header)
            continue;
        for (int j = 0; j < tile->header->polyCount; ++j) {
            if (g->membership[g->offsets[i] + j] >= 0)
                continue;
            int id = g->edges.size();
            g->edges.emplace_back();
            g->centers.emplace_back();
            int count = 0;
            stack.push_back(j);
            g->membership[g->offsets[i] + j] = id;
            while (!stack.empty()) {
                int v = stack.back();
                stack.pop_back();
                auto &poly = tile->polys[v];
                float xyz[3];
                center(tile, &poly, xyz);
                rcVadd(g->centers[id].xyz, g->centers[id].xyz, xyz);
                ++count;
                for (auto l = poly.firstLink; l != DT_NULL_LINK; l = tile->links[l].next) {
                    auto ref = tile->links[l].ref;
                    if (!ref || nav->decodePolyIdTile(ref) != (unsigned)i)
                        continue;
                    int w = nav->decodePolyIdPoly(ref);
                    auto &m = g->membership[g->offsets[i] + w];
                    if (m < 0) {
                        m = id;
                        stack.push_back(w);
                    }
                }
            }
            for (float &v : g->centers[id].xyz)
                v /= count;
        }
    }
    for (int i = 0; i < nav->getMaxTiles(); ++i) {
        auto *tile = nav->getTile(i);
        if (!tile->header)
            continue;
        for (int j = 0; j < tile->header->polyCount; ++j) {
            auto &peers = g->edges[g->membership[g->offsets[i] + j]];
            for (auto l = tile->polys[j].firstLink; l != DT_NULL_LINK; l = tile->links[l].next) {
                auto ref = tile->links[l].ref;
                if (!ref || nav->decodePolyIdTile(ref) == (unsigned)i)
                    continue;
                int next = g->cluster(nav, ref);
                if (std::find(peers.begin(), peers.end(), next) == peers.end())
                    peers.push_back(next);
            }
        }
    }
    return g;
}
API void free_clusters(ClusterGraph *graph) { delete graph; }
static std::vector<unsigned char> cluster_corridor(const ClusterGraph &g, int start, int end) {
    std::vector<int> parent(g.edges.size(), -1);
    std::vector<float> cost(g.edges.size(), INFINITY);
    std::priority_queue<OpenPoly> open;
    cost[start] = 0;
    open.push({0, 0, (dtPolyRef)start});
    while (!open.empty()) {
        auto n = open.top();
        open.pop();
        int v = (int)n.ref;
        if (n.cost > cost[v])
            continue;
        if (v == end) {
            std::vector<unsigned char> allowed(g.edges.size(), 0);
            for (; v >= 0; v = parent[v]) {
                allowed[v] = 1;
                for (int neighbor : g.edges[v])
                    allowed[neighbor] = 1;
            }
            return allowed;
        }
        for (int w : g.edges[v]) {
            float c = n.cost + distance(g.centers[v].xyz, g.centers[w].xyz);
            if (c >= cost[w])
                continue;
            cost[w] = c;
            parent[w] = v;
            open.push({c + distance(g.centers[w].xyz, g.centers[end].xyz), c, (dtPolyRef)w});
        }
    }
    return {};
}
// Detour's native query pool has a 16-bit node index. Recover long world routes
// using the same per-profile mesh and its actual portal links, with a growable
// pool.
static bool world_corridor(const dtNavMesh *nav, dtPolyRef start, dtPolyRef end,
                           std::vector<dtPolyRef> &path, const ClusterGraph *graph = nullptr,
                           const std::vector<unsigned char> *allowed = nullptr) {
    const dtMeshTile *tile;
    const dtPoly *poly;
    float goal[3];
    nav->getTileAndPolyByRefUnsafe(end, &tile, &poly);
    center(tile, poly, goal);
    std::unordered_map<dtPolyRef, RouteNode> nodes;
    std::priority_queue<OpenPoly> open;
    nodes.emplace(start, RouteNode{0, 0});
    open.push({0, 0, start});
    while (!open.empty()) {
        OpenPoly item = open.top();
        open.pop();
        if (item.ref == end) {
            path.clear();
            for (dtPolyRef p = end; p; p = nodes.at(p).previous)
                path.push_back(p);
            std::reverse(path.begin(), path.end());
            return true;
        }
        if (item.cost > nodes.at(item.ref).cost)
            continue;
        nav->getTileAndPolyByRefUnsafe(item.ref, &tile, &poly);
        float current[3];
        center(tile, poly, current);
        for (auto l = poly->firstLink; l != DT_NULL_LINK; l = tile->links[l].next) {
            auto next = tile->links[l].ref;
            if (!next || (allowed && !(*allowed)[graph->cluster(nav, next)]))
                continue;
            const dtMeshTile *nextTile;
            const dtPoly *nextPoly;
            nav->getTileAndPolyByRefUnsafe(next, &nextTile, &nextPoly);
            if (!(nextPoly->flags & 1))
                continue;
            float point[3];
            center(nextTile, nextPoly, point);
            float cost = item.cost + distance(current, point) *
                         .5f * (travelCost(poly->getArea()) + travelCost(nextPoly->getArea()));
            auto it = nodes.find(next);
            if (it != nodes.end() && cost >= it->second.cost)
                continue;
            nodes[next] = {cost, item.ref};
            open.push({cost + distance(point, goal), cost, next});
        }
    }
    return false;
}

// Codes: 1 complete, 0 endpoint outside tolerance, 2 disconnected, 3 query
// budget exhausted.
static int route_path(const dtNavMesh *nav, const ClusterGraph *graph, const float *start,
                      const float *goal, float *output, int capacity, int *points,
                      bool pavement = false) {
    *points = 0;
    dtNavMeshQuery q;
    if (dtStatusFailed(q.init(nav, 65535)))
        return -1;
    dtQueryFilter filter;
    for (int area = GenericFloor; area <= Footpath; ++area)
        filter.setAreaCost(area, travelCost(static_cast<unsigned char>(area)));
    if (pavement)
        filter.setIncludeFlags(pavementFlag);
    const float snap = pavement ? 0.20f : 1.5f;
    float nearA[3], nearB[3];
    dtPolyRef af = 0, bf = 0;
    if (dtStatusFailed(endpoint(q, filter, start, af, nearA, snap)) ||
        dtStatusFailed(endpoint(q, filter, goal, bf, nearB, snap)))
        return -2;
    if (!af || !bf)
        return 0;
    std::vector<dtPolyRef> corridor(capacity);
    int count = 0;
    if (graph && distance(nearA, nearB) > 256) {
        auto allowed = cluster_corridor(*graph, graph->cluster(nav, af), graph->cluster(nav, bf));
        if (!allowed.empty() && world_corridor(nav, af, bf, corridor, graph, &allowed))
            count = corridor.size();
    }
    dtStatus result;
    if (!count) {
        corridor.resize(capacity);
        result = q.findPath(af, bf, nearA, nearB, &filter, corridor.data(), &count, capacity);
        if (dtStatusFailed(result))
            return -3;
        if (result & (DT_OUT_OF_NODES | DT_BUFFER_TOO_SMALL)) {
            if (pavement)
                return 3;
            if (!world_corridor(nav, af, bf, corridor))
                return 2;
            count = (int)corridor.size();
        } else if ((result & DT_PARTIAL_RESULT) || !count || corridor[count - 1] != bf)
            return 2;
    }
    std::vector<dtPolyRef> entered(capacity);
    std::vector<float> bends(3 * capacity);
    result = q.findStraightPath(nearA, nearB, corridor.data(), count, bends.data(), nullptr,
                                entered.data(), points, capacity, DT_STRAIGHTPATH_ALL_CROSSINGS);
    if (dtStatusFailed(result))
        return -4;
    if (result & DT_BUFFER_TOO_SMALL)
        return 3;
    // Portal vertices carry coarse contour heights. Sample the detail surface
    // along each straight segment on this very corridor to preserve flyovers.
    int bendsCount = *points;
    *points = 0;
    auto emit = [&](const float *v) {
        if (*points >= capacity)
            return false;
        toGame(v, output + 3 * (*points)++);
        return true;
    };
    if (!emit(nearA))
        return 3;
    int cursor = 0;
    for (int i = 0; i + 1 < bendsCount; ++i) {
        auto ref = entered[i] ? entered[i] : af;
        while (cursor + 1 < count && corridor[cursor] != ref)
            ++cursor;
        const float *a = &bends[i * 3], *b = &bends[i * 3 + 3];
        float len = std::hypot(b[0] - a[0], b[2] - a[2]);
        int steps = std::max(1, (int)std::ceil(len));
        float last[3] = {a[0], output[(*points - 1) * 3 + 2], a[2]};
        float anchorY = last[1], minSlope = -INFINITY, maxSlope = INFINITY;
        int anchor = 0;
        for (int k = 1; k <= steps; ++k) {
            float p[3];
            dtVlerp(p, a, b, (float)k / steps);
            if (i + 2 == bendsCount && k == steps)
                dtVcopy(p, nearB);
            else {
                float h = 0;
                if (dtStatusFailed(q.getPolyHeight(ref, p, &h))) {
                    bool found = false;
                    for (int j = std::max(0, cursor - 2); j < std::min(count, cursor + 4); ++j) {
                        float hit[3];
                        bool over = false;
                        if (dtStatusSucceed(q.closestPointOnPoly(corridor[j], p, hit, &over)) &&
                            (over || std::hypot(hit[0] - p[0], hit[2] - p[2]) < 0.03f)) {
                            h = hit[1];
                            found = true;
                            break;
                        }
                    }
                    if (!found)
                        return 4;
                }
                p[1] = h;
            }
            float slope = (p[1] - anchorY) / (k - anchor);
            if (k > anchor + 1 && (slope < minSlope || slope > maxSlope)) {
                if (!emit(last))
                    return 3;
                anchor = k - 1;
                anchorY = last[1];
                minSlope = -INFINITY;
                maxSlope = INFINITY;
            }
            minSlope = std::max(minSlope, (p[1] - anchorY - 0.04f) / (k - anchor));
            maxSlope = std::min(maxSlope, (p[1] - anchorY + 0.04f) / (k - anchor));
            dtVcopy(last, p);
            if (k == steps && !emit(p))
                return 3;
        }
    }
    return 1;
}
API int query_cluster_path(const dtNavMesh *nav, const ClusterGraph *graph, const float *start,
                           const float *goal, float *output, int capacity, int *points) {
    return route_path(nav, graph, start, goal, output, capacity, points);
}
API int query_pavement_path(const dtNavMesh *nav, const float *start, const float *goal,
                            float *out, int cap, int *points) {
    return route_path(nav, nullptr, start, goal, out, cap, points, true);
}
API int query_path(const dtNavMesh *nav, const float *start, const float *goal, float *out, int cap,
                   int *points) {
    return query_cluster_path(nav, nullptr, start, goal, out, cap, points);
}
// Constrain a small input displacement to connected polygons, including a slide along an edge.
API int move_body(const dtNavMesh *nav, const float *start, const float *target, float *out) {
    dtNavMeshQuery query;
    if (dtStatusFailed(query.init(nav, 128))) return -1;
    dtQueryFilter filter;
    dtPolyRef ref = 0;
    float origin[3], desired[3], landed[3];
    if (dtStatusFailed(endpoint(query, filter, start, ref, origin)) || !ref) return 0;
    if (std::hypot(origin[0] - start[0], origin[2] + start[1]) > .16f ||
        std::abs(origin[1] - start[2]) > .45f) return 0;
    toNav(target, desired);
    dtPolyRef visited[128];
    int count = 0;
    float fraction, normal[3];
    auto st = query.raycast(ref, origin, desired, &filter, &fraction, normal, visited, &count, 128);
    if (dtStatusFailed(st) || (st & DT_BUFFER_TOO_SMALL) || !count) return 0;
    if (fraction >= 1.f) {
        dtVcopy(landed, desired);
    } else {
        const auto hitRef = visited[count - 1];
        st = query.moveAlongSurface(ref, origin, desired, &filter, landed, visited, &count, 128);
        const float step = std::hypot(desired[0] - origin[0], desired[2] - origin[2]);
        if (dtStatusFailed(st) || (st & DT_BUFFER_TOO_SMALL) || !count ||
            std::hypot(landed[0] - origin[0], landed[2] - origin[2]) > step + .01f ||
            std::hypot(landed[0] - desired[0], landed[2] - desired[2]) > step + .01f) {
            dtVlerp(landed, origin, desired, std::max(0.f, fraction - .0001f));
            visited[0] = hitRef;
            count = 1;
        }
    }
    float height;
    if (dtStatusFailed(query.getPolyHeight(visited[count-1], landed, &height))) {
        float closest[3];
        if (dtStatusFailed(query.closestPointOnPoly(visited[count-1], landed, closest, nullptr))) return 0;
        height = closest[1];
    }
    out[0] = landed[0]; out[1] = -landed[2]; out[2] = height;
    return 1;
}
API int query_levels(const dtNavMesh *nav, float x, float y, float *heights, int capacity) {
    dtNavMeshQuery q;
    if (dtStatusFailed(q.init(nav, 64)))
        return -1;
    dtQueryFilter filter;
    const float center[] = {x, 1200.f, -y};
    const float ext[] = {0.01f, 2400.f, 0.01f};
    dtPolyRef refs[512];
    int n = 0;
    auto st = q.queryPolygons(center, ext, &filter, refs, &n, 512);
    if (dtStatusFailed(st) || (st & DT_BUFFER_TOO_SMALL))
        return -2;
    std::vector<float> values;
    for (int i = 0; i < n; ++i) {
        float closest[3];
        bool over = false;
        if (dtStatusSucceed(q.closestPointOnPoly(refs[i], center, closest, &over)) && over)
            values.push_back(closest[1]);
    }
    std::sort(values.begin(), values.end());
    int size = 0;
    for (float z : values) {
        if (size && z - heights[size - 1] < 0.125f)
            continue;
        if (size >= capacity)
            return -3;
        heights[size++] = z;
    }
    return size;
}