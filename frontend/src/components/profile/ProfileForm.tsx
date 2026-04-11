"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MapPin } from "@phosphor-icons/react";

interface ProfileFormData {
  name: string;
  gender: "male" | "female" | "non-binary";
  interestedIn: "male" | "female" | "everyone";
  birthDate: string;
  birthTime?: string;
  bio: string;
  interests: string[];
  location?: { latitude: number; longitude: number };
}

interface ProfileFormProps {
  initialData?: Partial<ProfileFormData>;
  onSubmit: (data: ProfileFormData) => Promise<void>;
  submitLabel?: string;
}

const GENDER_OPTIONS = [
  { value: "male", label: "Male" },
  { value: "female", label: "Female" },
  { value: "non-binary", label: "Non-binary" },
] as const;

const INTERESTED_OPTIONS = [
  { value: "male", label: "Men" },
  { value: "female", label: "Women" },
  { value: "everyone", label: "Everyone" },
] as const;

const INTEREST_SUGGESTIONS = [
  "Travel", "Music", "Cooking", "Fitness", "Reading",
  "Photography", "Art", "Hiking", "Movies", "Gaming",
  "Yoga", "Dancing", "Coffee", "Wine", "Pets",
];

export function ProfileForm({ initialData, onSubmit, submitLabel = "Continue" }: ProfileFormProps) {
  const [name, setName] = useState(initialData?.name ?? "");
  const [gender, setGender] = useState<ProfileFormData["gender"]>(initialData?.gender ?? "male");
  const [interestedIn, setInterestedIn] = useState<ProfileFormData["interestedIn"]>(initialData?.interestedIn ?? "everyone");
  const [birthDate, setBirthDate] = useState(initialData?.birthDate ?? "");
  const [bio, setBio] = useState(initialData?.bio ?? "");
  const [interests, setInterests] = useState<string[]>(initialData?.interests ?? []);
  const [location, setLocation] = useState(initialData?.location ?? undefined);
  const [locating, setLocating] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function toggleInterest(interest: string) {
    setInterests((prev) =>
      prev.includes(interest)
        ? prev.filter((i) => i !== interest)
        : prev.length < 5
          ? [...prev, interest]
          : prev
    );
  }

  function handleLocate() {
    if (!navigator.geolocation) return;
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocation({ latitude: pos.coords.latitude, longitude: pos.coords.longitude });
        setLocating(false);
      },
      () => setLocating(false),
      { timeout: 10000 }
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (!name.trim() || !birthDate) {
      setError("Name and birth date are required.");
      return;
    }

    setLoading(true);
    try {
      await onSubmit({ name: name.trim(), gender, interestedIn, birthDate, bio: bio.trim(), interests, location });
    } catch (err: unknown) {
      const message = err && typeof err === "object" && "message" in err
        ? (err as { message: string }).message
        : "Failed to save profile.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {error && (
        <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="space-y-2">
        <Label htmlFor="name">Display Name</Label>
        <Input
          id="name"
          placeholder="Your name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={50}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="birthDate">Birth Date</Label>
        <Input
          id="birthDate"
          type="date"
          value={birthDate}
          onChange={(e) => setBirthDate(e.target.value)}
          required
          className="text-foreground"
        />
      </div>

      <div className="space-y-2">
        <Label>I am</Label>
        <div className="flex gap-2">
          {GENDER_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setGender(opt.value)}
              className={`flex-1 rounded-lg border px-3 py-2.5 text-sm transition-colors ${
                gender === opt.value
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:border-muted-foreground"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <Label>Interested in</Label>
        <div className="flex gap-2">
          {INTERESTED_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setInterestedIn(opt.value)}
              className={`flex-1 rounded-lg border px-3 py-2.5 text-sm transition-colors ${
                interestedIn === opt.value
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:border-muted-foreground"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="bio">Bio</Label>
        <textarea
          id="bio"
          placeholder="A few words about yourself..."
          value={bio}
          onChange={(e) => setBio(e.target.value)}
          maxLength={300}
          rows={3}
          className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none"
        />
        <p className="text-xs text-muted-foreground text-right">{bio.length}/300</p>
      </div>

      <div className="space-y-2">
        <Label>Interests <span className="text-muted-foreground font-normal">(up to 5)</span></Label>
        <div className="flex flex-wrap gap-2">
          {INTEREST_SUGGESTIONS.map((interest) => (
            <button
              key={interest}
              type="button"
              onClick={() => toggleInterest(interest)}
              className={`rounded-full px-3 py-1.5 text-xs transition-colors ${
                interests.includes(interest)
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              {interest}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <Label>Location</Label>
        <Button
          type="button"
          variant="outline"
          onClick={handleLocate}
          disabled={locating}
          className="w-full justify-start gap-2"
        >
          <MapPin size={18} />
          {location
            ? `${location.latitude.toFixed(2)}, ${location.longitude.toFixed(2)}`
            : locating
              ? "Getting location..."
              : "Enable location"}
        </Button>
      </div>

      <Button type="submit" className="w-full" disabled={loading}>
        {loading ? "Saving..." : submitLabel}
      </Button>
    </form>
  );
}
