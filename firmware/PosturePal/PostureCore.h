#pragma once
// Platform-independent geometry, calibration and alert logic. Angles are degrees.
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cerrno>
#include <cstring>

namespace pp {
constexpr double PI_D = 3.14159265358979323846;
constexpr double DEG = 180.0 / PI_D;
constexpr uint32_t STALE_US = 30000;
constexpr uint32_t GAP_US = 16000;
constexpr uint32_t MAX_SKEW_US = 12000;
inline double wrap(double x) { return std::remainder(x, 360.0); }
inline bool elapsed(uint32_t now, uint32_t then, uint32_t duration) {
  return uint32_t(now - then) >= duration;
}
struct Vec { double x, y, z; };
struct Alignment {
  double m[3][3]; // rows = anatomical forward, left, headward in sensor coordinates
  Vec apply(Vec v) const {
    return {m[0][0]*v.x+m[0][1]*v.y+m[0][2]*v.z,
            m[1][0]*v.x+m[1][1]*v.y+m[1][2]*v.z,
            m[2][0]*v.x+m[2][1]*v.y+m[2][2]*v.z};
  }
  bool valid() const {
    for (int i=0;i<3;i++) for (int j=0;j<3;j++) {
      double dot=0; for (int k=0;k<3;k++) dot+=m[i][k]*m[j][k];
      if (!std::isfinite(dot) || std::fabs(dot-(i==j ? 1.0 : 0.0))>1e-5) return false;
    }
    double det=m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
      -m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
      +m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]);
    return std::fabs(det-1)<1e-5;
  }
};
inline bool axis(const char* s, Vec& v) {
  if (!s || std::strlen(s)!=2 || (s[0]!='+' && s[0]!='-')) return false;
  double sign=s[0]=='+' ? 1 : -1; v={0,0,0};
  if(s[1]=='X') v.x=sign; else if(s[1]=='Y') v.y=sign;
  else if(s[1]=='Z') v.z=sign; else return false;
  return true;
}
inline bool makeAlignment(const char* head, const char* outward, Alignment& a) {
  Vec z,o; if(!axis(head,z)||!axis(outward,o)) return false;
  if(std::fabs(z.x*o.x+z.y*o.y+z.z*o.z)>0.1) return false;
  Vec x={-o.x,-o.y,-o.z};
  Vec y={z.y*x.z-z.z*x.y,z.z*x.x-z.x*x.z,z.x*x.y-z.y*x.x};
  a={{{x.x,x.y,x.z},{y.x,y.y,y.z},{z.x,z.y,z.z}}};
  return a.valid();
}
// q is Hamilton (w,x,y,z), sensor -> gravity-aligned earth frame.
// R(q)^T * earthUp is invariant to ANY left-multiplied world heading rotation.
inline bool upFromQuaternion(const double q[4], const Alignment& a, Vec& up) {
  double n=0; for(int i=0;i<4;i++) { if(!std::isfinite(q[i])) return false; n+=q[i]*q[i]; }
  if(std::fabs(n-1)>0.01) return false;
  double w=q[0],x=q[1],y=q[2],z=q[3];
  up=a.apply({2*(x*z-w*y)/n,2*(y*z+w*x)/n,(w*w-x*x-y*y+z*z)/n});
  return true;
}
inline bool tilts(Vec up, double& sagittal, double& lateral) {
  // Reject projections smaller than sin(10 degrees); outside the seated envelope.
  if(std::hypot(up.x,up.z)<0.174 || std::hypot(up.y,up.z)<0.174) return false;
  sagittal=std::atan2(-up.x,up.z)*DEG;
  lateral=std::atan2(up.y,up.z)*DEG;
  return std::isfinite(sagittal)&&std::isfinite(lateral);
}
inline void regions(const double tilt[6], double out[4]) {
  // tilts = sag T3,T12,L5, lateral T3,T12,L5; regions = upper/lower sag then lateral
  out[0]=wrap(tilt[0]-tilt[1]); out[1]=wrap(tilt[1]-tilt[2]);
  out[2]=wrap(tilt[3]-tilt[4]); out[3]=wrap(tilt[4]-tilt[5]);
}
struct Settings {
  double trigger[2]={7.5,7.5}, recovery[2]={4,4};
  uint32_t durationMs=2000;
  bool valid() const {
    for(int i=0;i<2;i++) if(!std::isfinite(trigger[i])||!std::isfinite(recovery[i])||
      recovery[i]<=0||trigger[i]<=recovery[i]||trigger[i]>90) return false;
    return durationMs>=1 && durationMs<=3600000;
  }
};
inline bool number(const char* token,double& out) {
  if(!token||!*token) return false;
  char* end=nullptr; errno=0; out=std::strtod(token,&end);
  return !errno && end!=token && !*end && std::isfinite(out);
}
inline bool parseSettings(char* const* tokens,int count,Settings& out) {
  if(count!=6||std::strcmp(tokens[0],"set")) return false;
  Settings s; double duration;
  if(!number(tokens[1],s.trigger[0])||!number(tokens[2],s.recovery[0])||
     !number(tokens[3],s.trigger[1])||!number(tokens[4],s.recovery[1])||
     !number(tokens[5],duration)||duration<1||duration>3600000||std::floor(duration)!=duration) return false;
  s.durationMs=uint32_t(duration); if(!s.valid()) return false; out=s; return true;
}
struct AlertLogic {
  bool timing[2]={false,false}, alert=false;
  uint32_t start[2]={0,0};
  void reset() { timing[0]=timing[1]=alert=false; start[0]=start[1]=0; }
  void update(const double deviation[2],uint32_t now,const Settings& s) {
    if(alert) {
      if(std::fabs(deviation[0])<=s.recovery[0] && std::fabs(deviation[1])<=s.recovery[1]) reset();
      return;
    }
    for(int i=0;i<2;i++) {
      if(std::fabs(deviation[i])>s.trigger[i]) {
        if(!timing[i]) { timing[i]=true; start[i]=now; }
        if(elapsed(now,start[i],s.durationMs)) alert=true;
      } else timing[i]=false;
    }
  }
};
struct Calibration {
  bool tracking=false;
  uint32_t startMs=0,count=0;
  double anchor[6]={},lo[6]={},hi[6]={},sumSin[4]={},sumCos[4]={};
  void reset() { tracking=false; count=0; for(int i=0;i<4;i++) sumSin[i]=sumCos[i]=0; }
  bool add(uint32_t now,const double tilt[6],const double regional[4],bool still) {
    if(!still) { reset(); return false; }
    if(!tracking) {
      reset(); tracking=true; startMs=now;
      for(int i=0;i<6;i++) { anchor[i]=tilt[i]; lo[i]=hi[i]=0; }
    }
    for(int i=0;i<6;i++) {
      double d=wrap(tilt[i]-anchor[i]);
      if(d<lo[i]) lo[i]=d; if(d>hi[i]) hi[i]=d;
      if(hi[i]-lo[i]>1.0) { reset(); return false; }
    }
    for(int i=0;i<4;i++) {
      sumSin[i]+=std::sin(regional[i]/DEG); sumCos[i]+=std::cos(regional[i]/DEG);
    }
    ++count;
    return elapsed(now,startMs,5000)&&count>=500;
  }
  void baseline(double out[4]) const { for(int i=0;i<4;i++) out[i]=std::atan2(sumSin[i],sumCos[i])*DEG; }
};
inline bool sampleGap(uint32_t now,uint32_t previous,bool haveSample) {
  return haveSample && elapsed(now,previous,GAP_US);
}
inline bool freshFrame(uint32_t now,const uint32_t stamps[3],uint32_t& skew) {
  uint32_t oldest=0,newest=UINT32_MAX;
  for(int i=0;i<3;i++) { uint32_t age=now-stamps[i]; if(age>=STALE_US) return false;
    if(age>oldest) oldest=age; if(age<newest) newest=age; }
  skew=oldest-newest; return skew<=MAX_SKEW_US;
}
} // namespace pp
