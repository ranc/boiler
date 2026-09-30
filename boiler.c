#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>

#define GPIO "/sys/class/gpio"
#define GPIO4 GPIO "/gpio4"
#define GPIO4_VAL GPIO4 "/value"

#define DBFILE "/home/pi/boiler/sched.data"
#define OVERRIDE_FILE "/home/pi/boiler/override.data"

#ifdef DEBUG
#define LOG(x) printf x
#else
#define LOG(x)
#endif

char *ltrim(char *s)
{
    while(isspace(*s)) s++;
    return s;
}

char *rtrim(char *s)
{
    char* back = s + strlen(s);
    while(isspace(*--back));
    *(back+1) = '\0';
    return s;
}

char *trim(char *s)
{
    return rtrim(ltrim(s));
}

int split(const char *del, char *str, char *args[], unsigned int maxArgs)
{
    if (maxArgs==0) return 0;
    args[0] = strtok(str, del);
    int i=0;
    while (args[i]!=NULL)
    {
        i++;
        if (i==maxArgs) break;
        args[i] = strtok(NULL, del);
    }
    return i;
}

void turn(int on)
{
    FILE *f = fopen(GPIO4_VAL, "wt");
    if (f==NULL)
    {
        perror("Error opening GPIO file " GPIO4_VAL);
        return;
    }
    fprintf(f, on ? "0": "1");
    fclose(f);
}

typedef struct {
    int day;
    int start_hour;
    int start_min;
    int end_hour;
    int end_min;
} day_entry_t;

int is_in_period(struct tm *ti, day_entry_t *dep)
{
    //ti->tm_hour, ti->tm_min
    if (dep->day!=0 && dep->day != ti->tm_wday+1) return 0;
    // day is right
    int now_min = ti->tm_hour*60 + ti->tm_min;
    int start_min = dep->start_hour*60 + dep->start_min;
    int end_min = dep->end_hour*60 + dep->end_min;

    return start_min <= now_min && now_min < end_min;
}

int read_day_entry(day_entry_t *dep, char *line)
{
    char *day_sched[2];
    if (split(" ", line, day_sched, 2)!=2) return 1;
    //LOG(("got day [%s]\n", day_sched[0]));
    //LOG(("got period [%s]\n", day_sched[1]));
    char *day = day_sched[0];
    char *period[2];
    if (split("-", day_sched[1], period, 2)!=2) return 1;
    char *start_time[2];
    char *end_time[2];
    if (split(":", period[0], start_time, 2)!=2) return 1;
    if (split(":", period[1], end_time, 2)!=2) return 1;
    LOG(("period [%s:%s to %s:%s]\n", trim(start_time[0]), trim(start_time[1]),
            trim(end_time[0]), trim(end_time[1])));

    dep->day = day[0]!='*' ? atoi(day) : 0;
    dep->start_hour = atoi(start_time[0]);
    dep->start_min = atoi(start_time[1]);
    dep->end_hour = atoi(end_time[0]);
    dep->end_min = atoi(end_time[1]);
    return 0;
}

int is_override_exist()
{
    return access(OVERRIDE_FILE, F_OK) != -1;
}

void clear_override()
{
    if (is_override_exist())
        remove(OVERRIDE_FILE);
}

void override(int min, int is_on)
{
    clear_override();
    FILE *f = fopen(OVERRIDE_FILE, "wt");
    fprintf(f, "%d %d\n", min, is_on);
    fclose(f);
}

void get_override_period(time_t *start, time_t *end, int *is_on)
{
    struct stat file_stat;

    stat(OVERRIDE_FILE, &file_stat);

    *start = file_stat.st_mtime;
    FILE *f = fopen(OVERRIDE_FILE, "rt");
    int min=0;
    *is_on=0;
    if (2!=fscanf(f, "%d %d", &min, is_on)) {
        fprintf(stderr, "Bad override syntax in file\n");
        fclose(f);
        end=start;
        return;
    }
    fclose(f);
    *end = *start+min*60;
}

void print_override()
{
    if (!is_override_exist())
    {
        printf("0\n");
        return;
    }
    time_t start,end;
    int is_on;
    get_override_period(&start, &end, &is_on);
    printf("1 %d %d %d\n", start, end, is_on);
}

int check_override()
{
    if (!is_override_exist()) return 0;
    time_t start,end;
    time_t now;
    int is_on;

    get_override_period(&start, &end, &is_on);
    time (&now);
    if (start<=now && now < end)
    {
        LOG(("override is %d for %d sec\n", is_on, end-start));
        turn(is_on);
        return 1;
    }
    LOG(("out of override period, clearing entry.\n"));
    clear_override(); // override period is over
    return 0;
}

void check()
{
    time_t rawtime;
    struct tm * ti;

    if (check_override())
        return;

    time ( &rawtime );
    ti = localtime ( &rawtime );
    LOG(("now is %d %d:%d\n", ti->tm_wday+1, ti->tm_hour, ti->tm_min));

    FILE *f=fopen(DBFILE, "rt");
    if (f==NULL) {
        perror("Error opening database file " DBFILE);
        return;
    }
    char * line = NULL;
    size_t len = 0;
    ssize_t read;
    int found=0;
    while ((read = getline(&line, &len, f)) != -1) {
        //LOG(("got line witch %d chars: %s\n",read, line));
        if (read<1) continue;
        if (line[0] == '#' || line[0] == '/') continue;

        day_entry_t de;
        if (read_day_entry(&de, line)) continue;
        if (is_in_period(ti, &de)) {
            found=1;
            break;
        }
    }
    free(line);
    printf("found %d\n", found);
    turn(found);
    fclose(f);
}

int main(int argc, char *argv[])
{
  if (argc<2 || 0==strcmp(argv[1], "stat")) {
     char buf[16] = {0};
     FILE *f = fopen(GPIO4_VAL, "rt");
     if (f==NULL) {
        perror("Error opening file " GPIO4_VAL);
        return -1;
     }
     fread(buf, 1, 16, f);
     printf("%s\n", buf[0]=='1' ? "off" : "on");
     fclose(f);
     return 0;
  }
  if (0==strcmp(argv[1], "on"))
  {
    turn(1);
    return 0;
  }
  if (0==strcmp(argv[1], "off"))
  {
    turn(0);
    return 0;
  }
  if (0==strcmp(argv[1], "check"))
  {
      check();
  }
  if (0==strcmp(argv[1], "override"))
  { // override <min> <1=on/0=off>
      if (argc<3) return -1;
      if  (0==strcmp(argv[2], "clear"))
      {
          clear_override();
          return 0;
      }
      if  (0==strcmp(argv[2], "print"))
      {
          print_override();
          return 0;
      }
      if (argc<4) return -1;
      int min = atoi(argv[2]);
      int is_on = atoi(argv[3]);
      override(min, is_on);
  }
}
