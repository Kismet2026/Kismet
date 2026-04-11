"use client";

import { useRouter } from "next/navigation";
import { useProfile } from "@/hooks/useProfile";
import { usePhotos } from "@/hooks/usePhotos";
import { useAuth } from "@/context/AuthContext";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { PencilSimple, SignOut, MapPin, Calendar, Heart } from "@phosphor-icons/react";
import { calculateAge } from "@/lib/utils";

export default function ProfilePage() {
  const router = useRouter();
  const { profile, loading } = useProfile();
  const { photos } = usePhotos();
  const { logout } = useAuth();

  if (loading) return <LoadingSpinner size={48} className="flex-1 py-20" />;

  if (!profile) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-4 gap-4">
        <p className="text-muted-foreground">No profile found</p>
        <Button onClick={() => router.push("/onboarding")}>Create Profile</Button>
      </div>
    );
  }

  const primaryPhoto = photos.find((p) => p.isPrimary) ?? photos[0];
  const initial = profile.name.charAt(0).toUpperCase();
  const bgColor = `hsl(${profile.name.charCodeAt(0) * 7 % 360}, 25%, 22%)`;

  return (
    <div className="flex-1 px-4 py-6 max-w-md mx-auto w-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Profile</h1>
        <Button
          variant="outline"
          size="sm"
          onClick={() => router.push("/profile/edit")}
          className="gap-1.5"
        >
          <PencilSimple size={16} />
          Edit
        </Button>
      </div>

      {/* Avatar + Name */}
      <div className="flex flex-col items-center mb-6">
        {primaryPhoto ? (
          <img
            src={primaryPhoto.url}
            alt={profile.name}
            className="w-28 h-28 rounded-full object-cover border-4 border-primary/20"
          />
        ) : (
          <div
            className="w-28 h-28 rounded-full flex items-center justify-center text-4xl font-bold text-foreground/40 border-4 border-primary/20"
            style={{ background: bgColor }}
          >
            {initial}
          </div>
        )}
        <h2 className="text-xl font-bold mt-3">
          {profile.name}
          {profile.birthDate && (
            <span className="font-normal text-muted-foreground">
              , {calculateAge(profile.birthDate)}
            </span>
          )}
        </h2>
        {profile.city && (
          <p className="text-sm text-muted-foreground flex items-center gap-1 mt-0.5">
            <MapPin size={14} /> {profile.city}
          </p>
        )}
      </div>

      {/* Info cards */}
      <div className="space-y-3">
        {profile.bio && (
          <div className="bg-card rounded-xl p-4">
            <p className="text-sm text-foreground leading-relaxed">{profile.bio}</p>
          </div>
        )}

        <div className="bg-card rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-2 text-sm">
            <Heart size={16} className="text-muted-foreground" />
            <span className="text-muted-foreground">Interested in</span>
            <span className="text-foreground capitalize ml-auto">{profile.interestedIn}</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Calendar size={16} className="text-muted-foreground" />
            <span className="text-muted-foreground">Birth date</span>
            <span className="text-foreground ml-auto">{profile.birthDate}</span>
          </div>
        </div>

        {profile.interests && profile.interests.length > 0 && (
          <div className="bg-card rounded-xl p-4">
            <p className="text-xs text-muted-foreground mb-2">Interests</p>
            <div className="flex flex-wrap gap-2">
              {profile.interests.map((interest) => (
                <span
                  key={interest}
                  className="rounded-full bg-primary/10 text-primary px-3 py-1 text-xs"
                >
                  {interest}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Photos grid */}
        {photos.length > 0 && (
          <div className="bg-card rounded-xl p-4">
            <p className="text-xs text-muted-foreground mb-2">Photos</p>
            <div className="grid grid-cols-3 gap-2">
              {photos.map((photo) => (
                <img
                  key={photo.photoId}
                  src={photo.url}
                  alt="Photo"
                  className="aspect-square rounded-lg object-cover"
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Logout */}
      <button
        onClick={() => {
          logout();
          router.push("/login");
        }}
        className="flex items-center justify-center gap-2 w-full mt-8 py-3 text-sm text-destructive hover:text-destructive/80 transition-colors"
      >
        <SignOut size={18} />
        Log Out
      </button>
    </div>
  );
}
