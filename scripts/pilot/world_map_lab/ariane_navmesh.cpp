// Native adapter for Recast/Detour 1.6.0. Public coordinates remain in the game's XYZ frame.
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
constexpr float cs = 0.5f, ch = 0.125f;
constexpr int tileCells = 256;
constexpr float tileWidth = tileCells * cs;

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

API int build_tile(const Chunk *chunks, int count, float originX, float originY, int tx, int ty,
                   float ymin, float ymax, int layer, int drive, unsigned char **out, int *bytes) {
    *out = nullptr;
    *bytes = 0;
    rcContext ctx(false);
    const int radius = drive ? 3 : 1;
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
    if (!init(solid) || !init(water) || (drive && !init(roads)))
        return -2;
    const float cosine = drive ? 0.906308f : 0.707107f;
    for (int k = 0; k < count; ++k) {
        const Chunk &batch = chunks[k];
        if (batch.kind == Paving || batch.kind == Foot || (!drive && batch.kind == Road))
            continue;
        rcHeightfield &target = batch.kind == Water ? water : batch.kind == Road ? roads : solid;
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
            if (batch.kind == Road && !area)
                continue;
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
            if (drive && s->area) {
                bool match = false;
                for (rcSpan *r = roads.spans[i]; r; r = r->next)
                    if (std::abs((int)r->smax - (int)s->smax) <= 3) {
                        match = true;
                        break;
                    }
                if (!match)
                    s->area = RC_NULL_AREA;
            }
        }
    }
    // This filter compares opposite neighbours, a two-cell baseline. Applying
    // the per-link climb here cuts ordinary road ramps into disconnected bands.
    // Compact-field links and cross-tile portals still use the single-step limit.
    rcFilterLedgeSpans(&ctx, height, drive ? 2 * climb : climb, solid);
    rcFilterWalkableLowHeightSpans(&ctx, height, solid);
    rcCompactHeightfield compact;
    if (!rcBuildCompactHeightfield(&ctx, height, climb, solid, compact))
        return -4;
    if (!compact.spanCount)
        return 0;
    if (!rcErodeWalkableArea(&ctx, radius, compact) ||
        !rcBuildRegionsMonotone(&ctx, compact, border, 12, 64))
        return -5;
    rcContourSet contours;
    if (!rcBuildContours(&ctx, compact, 0.75f, 32, contours, RC_CONTOUR_TESS_WALL_EDGES))
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
        mesh.areas[i] = 0;
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
    if (dtStatusFailed(nav->addTile(copy, size, DT_TILE_FREE_DATA, 0, nullptr))) {
        dtFree(copy);
        return 0;
    }
    return 1;
}
API void free_nav(dtNavMesh *nav) { dtFreeNavMesh(nav); }

// Collect exact static connectivity including cross-tile portals. Isolated polygons stay isolated.
struct Face {
    float xyz[18];
    uint32_t vertices, group;
};
API int collect_faces(const dtNavMesh *nav, Face *faces, int capacity) {
    std::vector<int> base(nav->getMaxTiles(), -1);
    int n = 0;
    for (int i = 0; i < nav->getMaxTiles(); ++i) {
        auto *t = nav->getTile(i);
        if (t->header) {
            base[i] = n;
            n += t->header->polyCount;
        }
    }
    if (!faces || capacity < n)
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
            auto &f = faces[base[i] + p];
            f.vertices = poly.vertCount;
            for (int v = 0; v < poly.vertCount; ++v)
                toGame(t->verts + poly.verts[v] * 3, f.xyz + v * 3);
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
    for (int i = 0; i < n; ++i)
        faces[i].group = root(i);
    return n;
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

// Detour's native query pool has a 16-bit node index. Recover long world routes
// using the same per-profile mesh and its actual portal links, with a growable pool.
static bool world_corridor(const dtNavMesh *nav, dtPolyRef start, dtPolyRef end,
                           std::vector<dtPolyRef> &path) {
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
            if (!next)
                continue;
            const dtMeshTile *nextTile;
            const dtPoly *nextPoly;
            nav->getTileAndPolyByRefUnsafe(next, &nextTile, &nextPoly);
            if (!(nextPoly->flags & 1))
                continue;
            float point[3];
            center(nextTile, nextPoly, point);
            float cost = item.cost + distance(current, point);
            auto it = nodes.find(next);
            if (it != nodes.end() && cost >= it->second.cost)
                continue;
            nodes[next] = {cost, item.ref};
            open.push({cost + distance(point, goal), cost, next});
        }
    }
    return false;
}

// Codes: 1 complete, 0 endpoint outside tolerance, 2 disconnected, 3 query budget exhausted.
API int query_path(const dtNavMesh *nav, const float *start, const float *goal, float *output,
                   int capacity, int *points) {
    *points = 0;
    dtNavMeshQuery q;
    if (dtStatusFailed(q.init(nav, 65535)))
        return -1;
    dtQueryFilter filter;
    const float bounds[] = {1.5f, 1.0f, 1.5f};
    float a[3], b[3], nearA[3], nearB[3];
    toNav(start, a);
    toNav(goal, b);
    dtPolyRef af = 0, bf = 0;
    if (dtStatusFailed(q.findNearestPoly(a, bounds, &filter, &af, nearA)) ||
        dtStatusFailed(q.findNearestPoly(b, bounds, &filter, &bf, nearB)))
        return -2;
    auto close = [](const float *p, const float *n) {
        return std::hypot(p[0] - n[0], p[2] - n[2]) <= 1.5f && std::abs(p[1] - n[1]) <= 1.0f;
    };
    if (!af || !bf || !close(a, nearA) || !close(b, nearB))
        return 0;
    std::vector<dtPolyRef> corridor(capacity);
    int count = 0;
    auto result = q.findPath(af, bf, nearA, nearB, &filter, corridor.data(), &count, capacity);
    if (dtStatusFailed(result))
        return -3;
    if (result & (DT_OUT_OF_NODES | DT_BUFFER_TOO_SMALL)) {
        if (!world_corridor(nav, af, bf, corridor))
            return 2;
        count = (int)corridor.size();
    } else if ((result & DT_PARTIAL_RESULT) || !count || corridor[count - 1] != bf)
        return 2;
    result = q.findStraightPath(nearA, nearB, corridor.data(), count, output, nullptr, nullptr,
                                points, capacity, DT_STRAIGHTPATH_ALL_CROSSINGS);
    if (dtStatusFailed(result))
        return -4;
    if (result & DT_BUFFER_TOO_SMALL)
        return 3;
    for (int i = 0; i < *points; ++i) {
        float v[3];
        std::memcpy(v, output + i * 3, sizeof(v));
        toGame(v, output + i * 3);
    }
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