import React, { useMemo } from 'react';
import { MapContainer, TileLayer, Marker, Circle, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

// Vite doesn't rewrite Leaflet's default marker image URLs to the bundled
// asset paths on its own -- without this the pin renders as a broken image.
const markerIconDefault = L.icon({
    iconUrl: markerIcon,
    iconRetinaUrl: markerIcon2x,
    shadowUrl: markerShadow,
    iconSize: [25, 41],
    iconAnchor: [12, 41],
});

const MIN_RADIUS_KM = 1;
const MAX_RADIUS_KM = 50; // Google's locationBias.circle.radius hard cap is 50000m.
const DEFAULT_RADIUS_KM = 25;

function ClickToPlace({ onPlace }) {
    useMapEvents({
        click(event) {
            onPlace({ lat: event.latlng.lat, lng: event.latlng.lng });
        },
    });
    return null;
}

export default function LocationPicker({ center, radiusKm, onChange, defaultView }) {
    const view = defaultView || { lat: 20.5937, lng: 78.9629, zoom: 5 }; // India, as a reasonable default

    const effectiveRadiusKm = radiusKm ?? DEFAULT_RADIUS_KM;

    const circleOptions = useMemo(() => ({ color: '#2563eb', fillColor: '#3b82f6', fillOpacity: 0.15 }), []);

    return (
        <div className="space-y-3">
            <div className="overflow-hidden rounded-2xl border border-slate-200" style={{ height: 320 }}>
                <MapContainer center={[view.lat, view.lng]} zoom={view.zoom} style={{ height: '100%', width: '100%' }}>
                    <TileLayer
                        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    />
                    <ClickToPlace onPlace={latlng => onChange({ ...latlng, radiusKm: effectiveRadiusKm })} />
                    {center && (
                        <>
                            <Marker position={[center.lat, center.lng]} icon={markerIconDefault} />
                            <Circle center={[center.lat, center.lng]} radius={effectiveRadiusKm * 1000} pathOptions={circleOptions} />
                        </>
                    )}
                </MapContainer>
            </div>

            <div className="flex items-center gap-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                <label className="text-sm font-medium text-slate-700 whitespace-nowrap">Radius: {effectiveRadiusKm} km</label>
                <input
                    type="range"
                    min={MIN_RADIUS_KM}
                    max={MAX_RADIUS_KM}
                    value={effectiveRadiusKm}
                    disabled={!center}
                    onChange={e => center && onChange({ ...center, radiusKm: Number(e.target.value) })}
                    className="flex-1 disabled:cursor-not-allowed disabled:opacity-60"
                />
            </div>

            <p className="text-xs text-slate-500">
                {center
                    ? `Center: ${center.lat.toFixed(4)}, ${center.lng.toFixed(4)} — searches a real ${effectiveRadiusKm}km-radius circle around this point.`
                    : 'Click on the map to place the center of your search area.'}
            </p>
        </div>
    );
}
