#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

using Clock = std::chrono::steady_clock;
using Ms = std::chrono::milliseconds;

struct Key {
  uint8_t k = 0;
  std::array<int,6> v{};
  bool operator==(const Key& o) const noexcept { return k==o.k && v==o.v; }
  bool operator<(const Key& o) const noexcept {
    if (k != o.k) return k < o.k;
    for (int i=0;i<6;i++) if (v[i]!=o.v[i]) return v[i]<o.v[i];
    return false;
  }
};
struct KeyHash {
  size_t operator()(const Key& x) const noexcept {
    uint64_t h=1469598103934665603ULL;
    h ^= x.k; h *= 1099511628211ULL;
    for(int i=0;i<x.k;i++){ h ^= (uint64_t)x.v[i] + 0x9e3779b97f4a7c15ULL + (h<<6)+(h>>2); h*=1099511628211ULL; }
    return (size_t)h;
  }
};
struct Rec { int forbidden=-1; int rhs=0; };
struct Eq { std::vector<int> row; int rhs=0; Key source; };
struct Row { std::vector<int> vars; int rhs=0; };

static inline double sec_since(Clock::time_point t){return std::chrono::duration<double>(Clock::now()-t).count();}
static inline long long ms_left(Clock::time_point deadline){return std::chrono::duration_cast<Ms>(deadline-Clock::now()).count();}

struct Header {int n=0; long long m=0;};
Header read_header(const std::string& path){
  std::ifstream f(path); std::string line;
  while(std::getline(f,line)){
    if(line.rfind("p cnf ",0)==0){std::istringstream ss(line);std::string p,cnf;Header h;ss>>p>>cnf>>h.n>>h.m;return h;}
  }
  throw std::runtime_error("missing p cnf header");
}

template<class Fn>
bool scan_cnf(const std::string& path, Fn fn, Clock::time_point deadline=Clock::time_point::max(), long long max_clauses=-1){
  std::ifstream f(path); if(!f) return false;
  std::string line; std::vector<int> cur; long long count=0;
  while(std::getline(f,line)){
    if(line.empty()) continue;
    char c=line[0]; if(c=='c') continue; if(c=='p') continue; if(c=='%') break;
    std::istringstream ss(line); long long x;
    while(ss>>x){
      if(x==0){
        if(!fn(cur)) return true;
        cur.clear(); count++;
        if(max_clauses>=0 && count>=max_clauses) return true;
        if((count&4095)==0 && Clock::now()>deadline) return false;
      } else cur.push_back((int)x);
    }
  }
  if(!cur.empty()) { fn(cur); }
  return Clock::now()<=deadline;
}

bool make_key(const std::vector<int>& clause, int maxk, Key& key, uint64_t& pattern){
  int k=(int)clause.size(); if(k<1||k>maxk) return false;
  std::array<std::pair<int,bool>,6> a{};
  for(int i=0;i<k;i++) a[i]={std::abs(clause[i]),clause[i]<0};
  for(int i=1;i<k;i++){auto x=a[i];int j=i;while(j>0&&a[j-1].first>x.first){a[j]=a[j-1];--j;}a[j]=x;}
  for(int i=1;i<k;i++) if(a[i].first==a[i-1].first) return false;
  key=Key{}; key.k=(uint8_t)k; pattern=0;
  for(int i=0;i<k;i++){key.v[i]=a[i].first;if(a[i].second) pattern|=1ULL<<i;}
  return true;
}
uint64_t parity_mask(int k,int parity){
  uint64_t mask=0; int lim=1<<k;
  for(int p=0;p<lim;p++) if((__builtin_popcount((unsigned)p)&1)==parity) mask|=1ULL<<p;
  return mask;
}
std::vector<int> key_vars(const Key& k){return std::vector<int>(k.v.begin(),k.v.begin()+k.k);}

struct Gate {bool candidate=false; double short_frac=0,dup_frac=0,wall=0; long long clauses=0;};
Gate sample_gate(const std::string& path,int maxk=6,long long maxc=4096){
  auto t=Clock::now(); std::unordered_set<Key,KeyHash> seen; long long total=0,sh=0,rep=0;
  scan_cnf(path,[&](const std::vector<int>& c){total++;Key k;uint64_t p;if(make_key(c,maxk,k,p)){sh++;if(!seen.insert(k).second)rep++;}return true;},Clock::time_point::max(),maxc);
  Gate g;g.clauses=total;g.short_frac=total?double(sh)/total:0;g.dup_frac=sh?double(rep)/sh:0;
  g.candidate=total>0&&g.short_frac>=0.95&&g.dup_frac>=0.25;g.wall=sec_since(t);return g;
}

struct Extract {
  Header h; std::unordered_map<Key,uint64_t,KeyHash> groups; std::unordered_map<Key,Rec,KeyHash> rec;
  std::vector<Key> group_order; std::vector<Eq> eqs; long long total=0; long long recognized_equiv=0; bool local_unsat=false; bool budget=false;
};
Extract extract(const std::string& path, Clock::time_point deadline,int maxk=6,size_t max_groups=2000000){
  Extract ex;ex.h=read_header(path);
  bool ok=scan_cnf(path,[&](const std::vector<int>& c){ex.total++;Key k;uint64_t p;if(make_key(c,maxk,k,p)){
      auto it=ex.groups.find(k);if(it!=ex.groups.end())it->second|=1ULL<<p;else{if(ex.groups.size()>=max_groups){ex.budget=true;return false;}ex.groups.emplace(k,1ULL<<p);ex.group_order.push_back(k);} }
    return Clock::now()<=deadline;},deadline);
  if(!ok||Clock::now()>deadline){ex.budget=true;return ex;}
  for(const Key& k: ex.group_order){uint64_t bits=ex.groups.at(k);uint64_t em=parity_mask(k.k,0),om=parity_mask(k.k,1);bool he=(bits&em)==em,ho=(bits&om)==om;
    if(he&&ho){ex.local_unsat=true;break;}
    if(he){ex.rec[k]=Rec{0,1};ex.eqs.push_back(Eq{key_vars(k),1,k});ex.recognized_equiv += 1LL<<(k.k-1);}
    else if(ho){ex.rec[k]=Rec{1,0};ex.eqs.push_back(Eq{key_vars(k),0,k});ex.recognized_equiv += 1LL<<(k.k-1);}
  }
  return ex;
}

std::vector<int> xor_rows(const std::vector<int>& a,const std::vector<int>& b){
  std::vector<int> out;out.reserve(a.size()+b.size());std::set_symmetric_difference(a.begin(),a.end(),b.begin(),b.end(),std::back_inserter(out));return out;
}
int largest_internal(const std::vector<int>& row,const std::vector<uint8_t>& boundary){for(auto it=row.rbegin();it!=row.rend();++it)if(!boundary[*it])return *it;return 0;}

struct BasisResult {bool unsat=false; std::unordered_map<int,Row> piv;};
BasisResult eliminate_all(const std::vector<Eq>& eqs,Clock::time_point deadline,size_t nnz_cap=8000000){
  BasisResult br;size_t nnz=0;int i=0;
  for(auto&e:eqs){std::vector<int> r=e.row;int rhs=e.rhs;
    while(!r.empty()){
      int p=r.back();auto it=br.piv.find(p);if(it==br.piv.end()){nnz+=r.size();if(nnz>nnz_cap)return BasisResult{false,{}};br.piv[p]=Row{r,rhs};r.clear();rhs=0;break;}
      r=xor_rows(r,it->second.vars);rhs^=it->second.rhs;if((++i&127)==0&&Clock::now()>deadline)return BasisResult{false,{}};
    }
    if(r.empty()&&rhs){br.unsat=true;return br;}
    if(Clock::now()>deadline)return BasisResult{false,{}};
  }
  return br;
}

struct Classification {long long other=0,removed=0;std::vector<uint8_t> boundary;std::vector<uint8_t> affine;bool budget=false;};
Classification classify(const std::string& path,const Extract& ex,Clock::time_point deadline,int maxk=6){
  Classification c;c.boundary.assign(ex.h.n+1,0);c.affine.assign(ex.h.n+1,0);for(auto&e:ex.eqs)for(int v:e.row)c.affine[v]=1;
  bool ok=scan_cnf(path,[&](const std::vector<int>& cl){bool isxor=false;Key k;uint64_t pat;if(make_key(cl,maxk,k,pat)){auto it=ex.rec.find(k);if(it!=ex.rec.end()&&((__builtin_popcountll(pat)&1)==it->second.forbidden))isxor=true;}
    if(isxor)c.removed++;else{c.other++;for(int lit:cl)c.boundary[std::abs(lit)]=1;}return Clock::now()<=deadline;},deadline);
  c.budget=!ok||Clock::now()>deadline;return c;
}

struct Projection {bool unsat=false;bool budget=false;std::unordered_map<int,Row> internal;std::unordered_map<int,Row> boundary_basis;std::vector<int> boundary_order;};
Projection project(const std::vector<Eq>& eqs,const std::vector<uint8_t>& boundary,Clock::time_point deadline,size_t nnz_cap=12000000){
  Projection pr;std::vector<Row> projected;size_t nnz=0;long long ops=0;
  for(auto&e:eqs){std::vector<int> r=e.row;int rhs=e.rhs;
    while(true){int p=largest_internal(r,boundary);if(!p)break;auto it=pr.internal.find(p);if(it==pr.internal.end()){nnz+=r.size();if(nnz>nnz_cap){pr.budget=true;return pr;}pr.internal[p]=Row{r,rhs};r.clear();rhs=0;break;}r=xor_rows(r,it->second.vars);rhs^=it->second.rhs;if((++ops&127)==0&&Clock::now()>deadline){pr.budget=true;return pr;}}
    if(!r.empty()||rhs) projected.push_back(Row{r,rhs});if(Clock::now()>deadline){pr.budget=true;return pr;}
  }
  for(auto rr:projected){auto r=std::move(rr.vars);int rhs=rr.rhs;while(!r.empty()){int p=r.back();auto it=pr.boundary_basis.find(p);if(it==pr.boundary_basis.end()){nnz+=r.size();if(nnz>nnz_cap){pr.budget=true;return pr;}pr.boundary_basis[p]=Row{r,rhs};pr.boundary_order.push_back(p);r.clear();rhs=0;break;}r=xor_rows(r,it->second.vars);rhs^=it->second.rhs;if((++ops&127)==0&&Clock::now()>deadline){pr.budget=true;return pr;}}
    if(r.empty()&&rhs){pr.unsat=true;return pr;}
  }
  return pr;
}

bool verify_model(const std::string& path,const std::vector<int8_t>& a){bool ok=true;scan_cnf(path,[&](const std::vector<int>& c){bool sat=false;for(int l:c){int v=std::abs(l);bool val=v<(int)a.size()&&a[v]>0;if((l>0&&val)||(l<0&&!val)){sat=true;break;}}if(!sat){ok=false;return false;}return true;});return ok;}
std::vector<int8_t> backsolve_full(int n,const std::unordered_map<int,Row>& piv){std::vector<int8_t>a(n+1,0);std::vector<int>ks;ks.reserve(piv.size());for(auto&kv:piv)ks.push_back(kv.first);std::sort(ks.begin(),ks.end());for(int p:ks){auto&r=piv.at(p);int val=r.rhs;for(int v:r.vars)if(v!=p)val^=(a[v]>0);a[p]=val?1:-1;}return a;}

std::string temp_path(const std::string& prefix){std::ostringstream ss;ss<<"/tmp/"<<prefix<<"_"<<getpid()<<"_"<<Clock::now().time_since_epoch().count();return ss.str();}
struct ProcRes {std::string status="ERROR",out;double wall=0;bool timeout=false;int rc=-1;};
ProcRes run_process(const std::vector<std::string>& args,int timeout_ms){
  ProcRes r;auto t=Clock::now();std::string op=temp_path("v15out");int fd=open(op.c_str(),O_CREAT|O_TRUNC|O_WRONLY,0600);if(fd<0)return r;
  pid_t pid=fork();if(pid==0){dup2(fd,STDOUT_FILENO);dup2(fd,STDERR_FILENO);close(fd);std::vector<char*> av;for(auto&s:args)av.push_back(const_cast<char*>(s.c_str()));av.push_back(nullptr);execv(av[0],av.data());_exit(127);}close(fd);int status=0;bool done=false;auto dl=Clock::now()+Ms(std::max(1,timeout_ms));
  while(Clock::now()<dl){pid_t w=waitpid(pid,&status,WNOHANG);if(w==pid){done=true;break;}std::this_thread::sleep_for(std::chrono::milliseconds(1));}
  if(!done){kill(pid,SIGKILL);waitpid(pid,&status,0);r.timeout=true;r.status="TIMEOUT";}else if(WIFEXITED(status)){r.rc=WEXITSTATUS(status);if(r.rc==10)r.status="SAT";else if(r.rc==20)r.status="UNSAT";else r.status="ERROR";}
  std::ifstream fi(op);std::ostringstream buf;buf<<fi.rdbuf();r.out=buf.str();unlink(op.c_str());r.wall=sec_since(t);return r;
}
std::vector<int8_t> parse_model(const std::string& text,int n){std::vector<int8_t>a(n+1,0);std::istringstream in(text);std::string line;while(std::getline(in,line)){if(line.rfind("v ",0)!=0)continue;std::istringstream ss(line.substr(2));long long x;while(ss>>x){if(!x)continue;int v=std::abs((int)x);if(v<=n)a[v]=x>0?1:-1;}}return a;}

bool write_projected(const std::string& input,const std::string& out,const Extract& ex,const Classification& cl,const Projection& pr,Clock::time_point deadline){
  std::ofstream f(out);if(!f)return false;long long nx=(long long)pr.boundary_basis.size();f<<"p cnf "<<ex.h.n<<" "<<(cl.other+nx)<<"\n";
  bool ok=scan_cnf(input,[&](const std::vector<int>& c){bool isxor=false;Key k;uint64_t pat;if(make_key(c,6,k,pat)){auto it=ex.rec.find(k);if(it!=ex.rec.end()&&((__builtin_popcountll(pat)&1)==it->second.forbidden))isxor=true;}if(!isxor){for(int l:c)f<<l<<' ';f<<"0\n";}return Clock::now()<=deadline;},deadline);
  if(!ok)return false;for(int p:pr.boundary_order){auto&r=pr.boundary_basis.at(p);if(r.vars.empty())continue;bool first=true;f<<'x';for(int v:r.vars){int lit=v;if(first&&r.rhs==0)lit=-lit;f<<' '<<lit;first=false;}f<<" 0\n";}return Clock::now()<=deadline;
}

std::vector<int8_t> reconstruct(int n,const Classification& cl,const Projection& pr,const std::vector<int8_t>& cms){std::vector<int8_t>a(n+1,-1);for(int i=1;i<=n;i++)if(cl.boundary[i])a[i]=(i<(int)cms.size()&&cms[i]!=0)?cms[i]:-1;for(int i=1;i<=n;i++)if(cl.affine[i]&&!cl.boundary[i])a[i]=-1;std::vector<int>ks;for(auto&kv:pr.internal)ks.push_back(kv.first);std::sort(ks.begin(),ks.end());for(int p:ks){auto&r=pr.internal.at(p);int val=r.rhs;for(int v:r.vars)if(v!=p)val^=(a[v]>0);a[p]=val?1:-1;}return a;}

void print_json_string(const std::string&s){std::cout<<'"';for(char c:s){if(c=='"'||c=='\\')std::cout<<'\\';std::cout<<c;}std::cout<<'"';}

int main(int argc,char**argv){
  if(argc<2){std::cerr<<"usage: v15_router input.cnf [--kissat PATH] [--cms PATH] [--budget-ms N] [--pre-ms N] [--mixed-ms N] [--analyze-only]\n";return 2;}
  std::string input=argv[1],kissat="",cms="";int budget_ms=10000,pre_ms=500,mixed_ms=2000;bool analyze_only=false;
  for(int i=2;i<argc;i++){std::string a=argv[i];auto next=[&](){if(i+1>=argc)throw std::runtime_error("missing option value");return std::string(argv[++i]);};if(a=="--kissat")kissat=next();else if(a=="--cms")cms=next();else if(a=="--budget-ms")budget_ms=std::stoi(next());else if(a=="--pre-ms")pre_ms=std::stoi(next());else if(a=="--mixed-ms")mixed_ms=std::stoi(next());else if(a=="--analyze-only")analyze_only=true;}
  auto start=Clock::now();auto total_deadline=start+Ms(budget_ms);Header h=read_header(input);Gate g=sample_gate(input);std::string route="abstain",status="UNKNOWN",proof="";bool model_ok=false;double solver_s=0;long long eqs=0,other=-1,internal=0,boundary_n=0,proj_n=0;double internal_frac=0,output_ratio=1;
  if(g.candidate && Clock::now()<total_deadline){
    auto pre_deadline=std::min(total_deadline,Clock::now()+Ms(pre_ms));Extract ex=extract(input,pre_deadline);eqs=ex.eqs.size();
    if(!ex.budget){
      if(ex.local_unsat){route="direct-affine";status="UNSAT";proof="algebraic-local";}
      else {
        Classification cl=classify(input,ex,pre_deadline);other=cl.other;
        if(!cl.budget){
          bool pure=(cl.other==0);
          if(pure){BasisResult br=eliminate_all(ex.eqs,pre_deadline);if(Clock::now()<=pre_deadline){route="direct-affine";if(br.unsat){status="UNSAT";proof="algebraic";}else{auto model=backsolve_full(h.n,br.piv);model_ok=verify_model(input,model);status=model_ok?"SAT":"ERROR";}}}
          else {
            for(int i=1;i<=h.n;i++){if(cl.affine[i]&&!cl.boundary[i])internal++;if(cl.boundary[i])boundary_n++;}
            internal_frac=h.n?double(internal)/h.n:0;Projection pr=project(ex.eqs,cl.boundary,pre_deadline);proj_n=pr.boundary_basis.size();output_ratio=h.m?double(cl.other+proj_n)/h.m:1;
            if(!pr.budget&&pr.unsat){route="mixed-affine-projection";status="UNSAT";proof="projection-algebraic";}
            else if(!pr.budget && internal_frac>=0.65 && output_ratio<=0.25 && !cms.empty() && Clock::now()<total_deadline){
              route="mixed-affine-projection";std::string xp=temp_path("v15proj")+".xnf";if(write_projected(input,xp,ex,cl,pr,pre_deadline)){
                int rem=(int)std::max<long long>(1,ms_left(total_deadline));int cap=std::min(mixed_ms,rem);std::vector<std::string>args={cms,"--verb=0","--threads=1","--presimp=1","--maxxormat=10000000","--maxmatrixrows=20000","--maxmatrixcols=20000","--xorfindtout=4000","--autodisablegauss=0",xp};ProcRes rr=run_process(args,cap);solver_s+=rr.wall;if(rr.status=="SAT"){auto cm=parse_model(rr.out,h.n);auto model=reconstruct(h.n,cl,pr,cm);model_ok=verify_model(input,model);status=model_ok?"SAT":"ERROR";}else if(rr.status=="UNSAT"){status="UNSAT";proof="projection+cms-xor";}else status=rr.status;unlink(xp.c_str());
              }
            }
          }
        }
      }
    }
  }
  if(analyze_only){if(status=="UNKNOWN")status="ABSTAIN";}
  else if((status=="UNKNOWN"||status=="TIMEOUT") && !kissat.empty() && Clock::now()<total_deadline){route="kissat";int rem=(int)std::max<long long>(1,ms_left(total_deadline));ProcRes rr=run_process({kissat,"--quiet","--seed=0",input},rem);solver_s+=rr.wall;status=rr.status;if(status=="SAT"){auto m=parse_model(rr.out,h.n);model_ok=verify_model(input,m);if(!model_ok)status="ERROR";}if(status=="UNSAT")proof="kissat";}
  double total=sec_since(start);
  std::cout<<"{";std::cout<<"\"file\":";print_json_string(input);std::cout<<",\"n\":"<<h.n<<",\"m\":"<<h.m<<",\"status\":";print_json_string(status);std::cout<<",\"route\":";print_json_string(route);std::cout<<",\"total_s\":"<<total<<",\"solver_s\":"<<solver_s<<",\"sample_s\":"<<g.wall<<",\"short_frac\":"<<g.short_frac<<",\"dup_frac\":"<<g.dup_frac<<",\"equations\":"<<eqs<<",\"other_clauses\":"<<other<<",\"internal_affine_vars\":"<<internal<<",\"boundary_vars\":"<<boundary_n<<",\"projected_xors\":"<<proj_n<<",\"internal_frac\":"<<internal_frac<<",\"output_ratio\":"<<output_ratio<<",\"model_ok\":"<<(model_ok?"true":"false")<<",\"proof\":";print_json_string(proof);std::cout<<"}\n";
  return status=="SAT"?10:status=="UNSAT"?20:0;
}
